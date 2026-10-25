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

Every finding from the first three sweeps has been fixed and is in
[`audit-finding-solved-logs.md`](audit-finding-solved-logs.md). Everything below was raised on
2026-10-04 or 2026-10-24 and is still open; what was fixed on 2026-10-17 is in the log.

| # | Finding | Severity | Raised |
| --- | --- | --- | --- |
| §U3.5 | `/settings/feedback` says "No feedback yet" when filters exclude everything | 🟡 | 2026-10-04 |
| §U3.6 | `/settings/feedback` applies URL-only filters the screen cannot show or clear | 🟡 | 2026-10-04 |
| §U3.7 | Eval tables have no pagination and stop at 100 rows | 🟡 | 2026-10-04 |
| §U4.7 | The "Negative" test-case badge is coloured at two call sites | 🟡 | 2026-10-04 |
| §U5.9 | The generate-eval-set dialog: two unassociated labels and a silent blank name | 🟡 | 2026-10-04 |
| §U5.10 | The eval sizes 10/25/50 restate a backend rule without saying so | 🟡 | 2026-10-04 |
| §U5.11 | The thumbs-down popover keeps stale reasons and sits outside the form contract | 🟡 | 2026-10-04 |
| §U7.15 | The eval sets empty state has no action, and `ListError` sits flush in two cards | 🟡 | 2026-10-04 |
| §U8.10 | A stray separator in the mock-data change-set card | 🟡 | 2026-10-04 |
| §U8.11 | A stored interrupted answer is worded differently from the live one | 🟡 | 2026-10-04 |
| §U9.5 | The eval set route answers a missing permission with `NotFound`, not `Forbidden` | 🟡 | 2026-10-04 |
| §U9.7 | Admin screens request data before their admin gate | 🟡 | 2026-10-04 |
| §U10.13 | Identifiers on the eval screens are in the body face | 🟡 | 2026-10-04 |
| §U10.14 | Off-scale spacing and a `text-[10px]` badge | 🟡 | 2026-10-04 |
| §U11.6 | Excluded pairs and pressed thumbs are signalled by colour alone | 🟡 | 2026-10-04 |
| §U11.7 | Eval run rows are clickable without a visible or accessible control | 🟡 | 2026-10-04 |
| §U11.8 | The compare selects and the date filters lose their visible labels | 🟡 | 2026-10-04 |
| §U1.5 | The web manifest repeats two theme colours as raw hex | 🟡 | 2026-10-24 |
| §U3.8 | Notification timestamps have no absolute time on hover | 🟡 | 2026-10-24 |
| §U3.9 | The feedback table's date is a raw `YYYY-MM-DD` in every language | 🟡 | 2026-10-24 |
| §U4.8 | Five more states pick their colour at the call site | 🟡 | 2026-10-24 |
| §U5.12 | Three more labels are not tied to their control | 🟡 | 2026-10-24 |
| §U5.13 | Three fields have no inline error to show a rejection | 🟡 | 2026-10-24 |
| §U5.14 | The translate dialog restates the backend's "English sources only" rule | 🟡 | 2026-10-24 |
| §U6.17 | Single-sentence messages end in a full stop, and four small copy splits | 🟡 | 2026-10-24 |
| §U6.18 | The not-found, in-progress and server error messages say what happened, not what to do | 🟡 | 2026-10-24 |
| §U6.19 | Three destructive confirmations do not say what is lost | 🟡 | 2026-10-24 |
| §U7.19 | Notification preferences load with no skeleton | 🟡 | 2026-10-24 |
| §U8.17 | The "thinking" label is looked up two ways | 🟡 | 2026-10-24 |
| §U8.18 | The two refinement chats' stream readers and panels are near-verbatim copies | 🟡 | 2026-10-24 |
| §U10.15 | Two new off-scale spacings | 🟡 | 2026-10-24 |
| §U10.16 | A small-caps "eyebrow" style outside the type scale | 🟡 | 2026-10-24 |
| §U10.17 | The module list shows its source path in the body face | 🟡 | 2026-10-24 |
| §U10.18 | A long module name in the export picker may be cut with no way to read it (SUSPECT) | 🟡 | 2026-10-24 |

## Top priorities (2026-10-24)

1. **Japanese, Korean and Chinese users cannot type a question reliably** (§U8.15). Pressing Enter
   to pick a character sends the half-typed question, on Ask and both refinement chats. This shipped
   with the languages it breaks, and the fix is one line.
2. **Three screens report an outage as "nothing here"** (§U7.17, §U7.18, §U6.15). The new export
   screen says a project has no modules, and the Ask picker says there is no matching project, when
   in fact the request failed. "Re-index now" on Ask does nothing visible when it fails.
3. **Keyboard and screen-reader gaps** (§U11.9, §U11.10, §U5.12, §U6.20, plus the open §U5.9 and
   §U11.6–§U11.8). Three checklist filters have no name at all. Ask's composer shows no focus ring.
   Every dialog's Close button is announced in English.
4. **Contrast in light mode** (§U1.4). White text on the success, info and danger badges is 2.2–3.8
   to 1, against a 4.5 target.
5. **Small false or missing states**:
   - §U8.14: the chats say "no permission" while the project loads.
   - §U8.16 and §U8.13: a cut-off reply looks complete in the refinement chats.
   - §U7.16: a vote briefly reverts.
   - §U3.5 and §U3.6: the feedback screen's filter states.
   - §U6.16: the signed-out language picker.
6. **Copy** (§U6.17–§U6.19), **hygiene** (§U1.5, §U3.8, §U3.9, §U4.7, §U4.8, §U5.13, §U5.14,
   §U7.19, §U8.17, §U8.18, §U10.13–§U10.18), and **documentation** (§U12.6–§U12.14).

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

Every finding this sweep raised here (§U6.12–§U6.14) was resolved on 2026-10-17 and is in
[`audit-finding-solved-logs.md`](audit-finding-solved-logs.md).

## U7 Loading, empty and error

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

## U8 The streaming surfaces

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

### §U1.5 The web manifest repeats two theme colours as raw hex — 🟡 hygiene

**Evidence:** CONFIRMED.

**Where:** `app/manifest.ts:23-24`; `app/globals.css:14-15`

**What this is.** `globals.css` is meant to be the only file with a raw hex colour. Every component
names a token instead.

**Why this can happen.** A web manifest is JSON served to the browser and cannot read a CSS
variable. So `theme_color` and `background_color` copy `#615fff` and `#f1f5f9` by hand.

**What it costs.** If the primary or background token changes, the installed-app chrome keeps the
old colour, and nothing points at the copy.

**What we should do.** Add a comment naming the two tokens it mirrors, and list the manifest as the
one allowed exception in `.claude/rules/design-system.md`. Five minutes.

## U3 The list skeleton

### §U3.8 Notification timestamps have no absolute time on hover — 🟡 hygiene

**Evidence:** CONFIRMED.

**Where:** `components/notifications/notification-list.tsx:56-58`

**What this is.** Every list shows relative time ("3 hours ago") with the exact time as its `title`,
through `formatRelative`/`formatAbsolute` (`docs/design.md` → Lists).

**Why this can happen.** The notification row renders `formatRelative` alone, and this one list is
used on `/notifications` and in the bell.

**What it costs.** On these screens alone, hovering a time shows nothing.

**What we should do.** Add `title={formatAbsolute(n.createdAt)}`. Five minutes.

### §U3.9 The feedback table's date is a raw `YYYY-MM-DD` in every language — 🟡 hygiene

**Evidence:** CONFIRMED.

**Where:** `components/output-feedback/feedback-table.tsx:~51-53`; `lib/api/types.ts:126`

**What this is.** Admins see the day of a vote and never its time. That is deliberate
(`.claude/rules/feedback.md` rule 2), so a relative "3 hours ago" is not possible here.

**Why this can happen.** `formatDay` prints the ISO string as-is. Every other date in the app is
formatted for the active locale.

**What it costs.** A Japanese or Korean admin sees `2026-10-24` while every other date on screen is
localised. The column also looks unlike its neighbours without saying why.

**What we should do.** Format the day with the active locale (date only, no time). Note the date-only
exception in `docs/design.md` → Lists. Fifteen minutes.

## U4 Status and semantic colour

### §U4.8 Five more states pick their colour at the call site — 🟡 hygiene

**Evidence:** CONFIRMED.

**Where:**
- `components/checklist/module-table.tsx:84`: `tone="warning"` for "Review changes".
- `components/checklist/module-table.tsx:94`: `text-danger` on the fail count.
- `components/change-sets/operation-groups.tsx:66`, `:82`: add, change and remove headings.
- `components/eval/eval-pair-table.tsx:93`: `text-warning` for "unfaithful translation".
- `components/eval/eval-run-sheet.tsx:83`: `text-warning` for grounding warnings.

**What this is.** `.claude/rules/design-system.md` §5 says every status maps to a tone in exactly one
module, `lib/status.ts`. Project, module, item result, audit outcome, eval status and eval verdict
all do.

**Why this can happen.** These five have no mapping, so each call site chose its own colour. Four
are new since `df7594e`, and they are the same family as the open §U4.7.

**What it costs.** Nothing is false today, because each choice is sensible. The next screen to show
a pending change set or an operation kind has nothing to copy, so it can choose differently.

**What we should do.** Add `changeSetOperationTone` and a pending-change-set tone to
`lib/status.ts`, and route these sites through it, together with §U4.7. One hour.

## U5 Forms

### §U5.12 Three more labels are not tied to their control — 🟡 hygiene

**Evidence:** CONFIRMED.

**Where:**
- `app/(app)/checklist/export/export-screen.tsx:154`, `:166`: the project combobox.
- `components/checklist/create-module-dialog.tsx:108`.
- `components/eval/translate-eval-set-dialog.tsx:86`: the language select.

**What this is.** `.claude/rules/forms.md` requires every control to have an `id` and its
`FieldLabel` a matching `htmlFor`. Tests and screen readers both find controls by label.

**Why this can happen.** These three `FieldLabel`s have no `htmlFor`, and their controls carry only
an `aria-label`. This is the same shape as the open §U5.9, and two of the three are new.

**What it costs.** Clicking the label does nothing. A screen reader reads the `aria-label`, which
can drift from the visible text.

**What we should do.** Give each control an `id` and each label its `htmlFor`. Fifteen minutes.

### §U5.13 Three fields have no inline error to show a rejection — 🟡 hygiene

**Evidence:** CONFIRMED. The trigger needs the backend to reject a value the frontend sends. Today
that happens only if the two language lists drift, and a test exists to stop that.

**Where:** `components/projects/create-project-dialog.tsx:115-127` (`contentLanguage`; compare `:67-69`);
`components/eval/generate-eval-set-dialog.tsx` (`count`, `mix`); `components/form/form-error.tsx:13`

**What this is.** Under the one-error-surface rule (`.claude/rules/forms.md`), a `422` that names a
field shows inline under that field. The form-level banner appears only when no field was named.

**Why this can happen.** These three fields never ask for their field error. So a `422` naming only
`contentLanguage`, `count` or `mix` hides the banner, because a field was named, and shows nothing
inline, because nobody asked.

**What it costs.** The dialog stays open, the button re-enables, and nothing says why.

**What we should do.** Add `fieldErrorText(mutation.error, …)` and a `FieldError` to each. Fifteen
minutes.

### §U5.14 The translate dialog restates the backend's "English sources only" rule — 🟡 hygiene

**Evidence:** CONFIRMED.

**Where:** `components/eval/translate-eval-set-dialog.tsx:19` (`TARGETS = LANGUAGES.filter(l => l !== "en")`);
`components/eval/eval-set-screen.tsx:192`

**What this is.** `.claude/rules/forms.md` limits client checks to required fields and shape. The
backend owns its rules.

**Why this can happen.** The dialog hard-codes that only English sets are translated, and only into
the other six languages. The screen hard-codes when the Translate button appears.

**What it costs.** If the backend widens the rule, the button stays hidden and the user never
learns. That is the same cost as §U5.10.

**What we should do.** Say so in a comment that names the backend rule. Better, have the set read
carry a `translatable` flag. Half an hour.

## U6 Feedback and copy

### §U6.17 Single-sentence messages end in a full stop, and four small copy splits — 🟡 hygiene

**Evidence:** CONFIRMED.

**Where:**
- `messages/en/ask.json:63` (`preflight.genericError` "Something went wrong.").
- `messages/en/errors.json`: the single-sentence entries, such as `VALIDATION_ERROR` (line 3),
  `INTERNAL_ERROR` (line 4) and the "… not found." group.
- Contractions: `messages/en/notifications.json:10`, `messages/en/profile.json:82`.
- Discard titles: `messages/en/checklist.json:179`, `messages/en/mockData.json:33`.
- Possibly unused: `messages/en/eval.json:37-38` (`titleNamed` beside `title`).

**What this is.** `docs/design.md` → Feedback says feedback copy has no trailing period. The owner
decided on 2026-10-24 that copy of two or more sentences keeps its stops (§U12.14), so only
single-sentence copy is in scope here.

**Why this can happen.** The single-sentence strings above end in a period, and they reach toasts
through `toast.error(errorText(e))` at nine call sites. Around them are four smaller splits:
- "Couldn't" in two strings, where the rest of the catalogue writes "could not".
- Both "Discard proposed changes" confirm titles have no "?", unlike every other confirm title.
- `titleNamed` and `title` sit side by side, and one is probably unused.
- "That did not save. Try again" (`messages/en/eval.json:54`) is the one multi-sentence string with
  no final stop.

**What it costs.** Toasts read as assembled by different hands. It is cosmetic.

**What we should do.** Drop the period from single-sentence entries, write "could not", add the
question marks, and remove whichever title key is unused. One hour, including all seven locales.

### §U6.18 The not-found, in-progress and server error messages say what happened, not what to do — 🟡 hygiene

**Evidence:** CONFIRMED.

**Where:** `messages/en/errors.json`:
- `VALIDATION_ERROR` (line 3), `INTERNAL_ERROR` (line 4), `INVALID_TOKEN` (line 5),
  `ADMIN_REQUIRED` (line 11).
- Every `*_NOT_FOUND` entry: users, projects, conversations, sessions, modules, items, both kinds
  of change set, records, eval sets and runs, roles, audit events, notifications, feedback targets.
- `EVAL_SET_NOT_READY` and both `*_GENERATION_IN_PROGRESS` entries.

**What this is.** `docs/design.md` → Feedback asks error copy to say what to do next. The frontend
picks a message by the backend's error code, and every one of the backend's 56 codes has an entry.

**Why this can happen.** These entries state the condition only: "Project not found.", "Internal
server error.", "Request validation failed.". A user who reaches one from a stale tab is left with a
dead end. `INTERNAL_ERROR` also reads as a developer's message.

**What we should do.** Add the next step to each. For not-found, that is "It may have been deleted;
refresh the list". For in-progress, "Wait for it to finish". For `INTERNAL_ERROR`, "Something went
wrong on our side. Try again, and tell an administrator if it keeps happening". One to two hours
across seven locales.

### §U6.19 Three destructive confirmations do not say what is lost — 🟡 hygiene

**Evidence:** CONFIRMED.

**Where:** `messages/en/mockData.json:4-5` (delete a record); `messages/en/projects.json:116-121`
(remove a member); `messages/en/roles.json:29-31` (delete a role)

**What this is.** A destructive confirmation names what is destroyed and what goes with it. Project,
module, test case, eval set and clear-results all do.

**Why this can happen.** Deleting a record says only "This cannot be undone." Removing a member
says they lose access, but not that their conversations and recorded results stay, or that they can
be added back. Deleting a role uses a bare "Delete" button, where every other dialog names its
object ("Delete project").

**What we should do.** Name the record, say what survives a removal, and write "Delete role". Half
an hour.

## U7 Loading, empty and error

### §U7.19 Notification preferences load with no skeleton — 🟡 hygiene

**Evidence:** CONFIRMED.

**Where:** `components/notifications/preferences-screen.tsx:~56-95`

**What this is.** A loading list shows skeleton rows shaped like the settled layout, so nothing jumps
(`docs/design.md` → Lists). The profile's Language and Answer style sections do.

**Why this can happen.** While loading, the preferences table renders its header with zero rows,
then the rows pop in.

**What we should do.** Render `TableSkeleton` while loading. Fifteen minutes.

## U8 The streaming surfaces

### §U8.17 The "thinking" label is looked up two ways — 🟡 hygiene

**Evidence:** CONFIRMED.

**Where:** `app/(app)/ask/[conversationId]/conversation-screen.tsx:~125`; `hooks/use-phase-label.ts`

Both chats use `usePhaseLabel`, whose comment says it exists so all three surfaces say the same
thing. Ask inlines its own `t.has("phases.…")` lookup. The output is identical today, and the next
change to one will not reach the other. **Fix:** use the hook on Ask. Five minutes.

### §U8.18 The two refinement chats' stream readers and panels are near-verbatim copies — 🟡 hygiene

**Evidence:** CONFIRMED.

**Where:** `lib/checklist/stream.ts` vs `lib/mock-data/stream.ts`;
`components/checklist/chat-panel.tsx` vs `components/mock-data/chat-panel.tsx`

The two stream readers differ only in the change-set event's name. The two panels differ only in
copy, query keys and endpoints. `components/mock-data/chat-panel.tsx` says the copy is deliberate.
The cost is that §U8.13 and §U8.16 each have to be fixed twice. **Fix:** one reader parameterised by
the event name. The panels can stay separate. One hour.

## U10 Layout, spacing, typography

### §U10.15 Two new off-scale spacings — 🟡 hygiene

**Evidence:** CONFIRMED.

**Where:** `components/profile/profile-screen.tsx:91` (`lg:top-24`, `lg:w-48`);
`components/form/password-input.tsx:35` (`pe-10`)

Spacing comes from the steps 1, 2, 3, 4, 6, 8 and 12 (`docs/design.md:147`). The only documented
exception is `pl-9` (`:158`). These two are new since `df7594e`. The rest of §U10.14's set is
unchanged. **Fix:** move them onto the scale, or document them beside `pl-9`. Fifteen minutes.

### §U10.16 A small-caps "eyebrow" style outside the type scale — 🟡 hygiene

**Evidence:** CONFIRMED.

**Where:** `components/audit/audit-change-list.tsx:92`; `components/audit/audit-event-detail.tsx:29`,
`:126`; `components/eval/eval-pair-table.tsx:137`

**What this is.** `docs/design.md:84-90` defines seven type styles, and a section title is
`text-xl font-semibold` (`:108-109`).

**Why this can happen.** Four places use `text-xs font-medium tracking-wide uppercase`, which is not
in the scale. One of them is an `<h2>` (`audit-event-detail.tsx:126`).

**What it costs.** In English these labels are tracked capitals. `uppercase` does nothing to
Japanese, Korean or Chinese text, so the same label looks like a different element in those
languages.

**What we should do.** Either add the eyebrow as an eighth scale row, or use the muted `text-sm`
label style. Fifteen minutes.

### §U10.17 The module list shows its source path in the body face — 🟡 hygiene

**Evidence:** CONFIRMED.

**Where:** `components/checklist/module-table.tsx:61-63`. Related: `app/(app)/checklist/[moduleId]/module-screen.tsx:337`
(SUSPECT, because the catalogue string would need a `<path>` tag)

File paths are `font-mono text-sm` everywhere (`docs/design.md:80`, `:90`). The project, eval and
path-picker screens now follow it, and this column does not. **Fix:** add `font-mono`. Five
minutes.

### §U10.18 A long module name in the export picker may be cut with no way to read it — 🟡 hygiene

**Evidence:** SUSPECT. Unverified: whether the label is width-limited. Rendering a module with an
80-character name settles it.

**Where:** `app/(app)/checklist/export/export-screen.tsx:247` (`FieldLabel … className="truncate"`)

The label truncates and has no `title`. Two modules whose names share a long prefix would then look
identical. **Fix:** add `title={module.name}`, or let the label wrap. Five minutes.

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
