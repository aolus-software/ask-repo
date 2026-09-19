# UI audit findings

**Swept:** 2026-09-13 · **Scope:** the whole of `frontend/` — every flow from `/login` through
the admin user screens, with the emphasis the sweep was asked for: forms, cards, tables,
filters, dialogs, drawers, confirmations, and error states.

**Ground truth:** [`docs/design.md`](design.md), `.claude/rules/design-system.md`,
`.claude/rules/forms.md`, `.claude/rules/navigation.md`, `frontend/app/globals.css`, and
[`docs/PRD.md`](PRD.md), which outranks them all.

**This sweep itself was read-only** — not one component, token, or stylesheet was changed by
`/audit-ui`. A separate, explicitly requested fix pass on 2026-09-13 then resolved every
CONFIRMED finding below except the two noted as partial. Each resolved finding's heading is
marked `— ✅ RESOLVED 2026-09-13` with a quote block saying what changed and where, and the
original finding text stays below it under "Original finding follows.", per
`.claude/rules/audit-findings.md`.

**Resolved 2026-09-13, in one pass:** §U1.2, §U2.1, §U2.2, §U2.3, §U3.1, §U3.2, §U3.3, §U4.2,
§U4.3, §U5.1, §U5.3, §U5.4, §U5.5, §U5.6, §U6.1, §U6.2, §U6.3, §U6.4, §U7.1, §U7.2, §U7.3, §U8.1,
§U8.2, §U8.3, §U8.4 (defensive fix; the SUSPECT question itself was not separately settled),
§U9.2, §U10.2, §U10.4, §U11.2, §U12.1, §U12.2, §U12.3. **Resolved with a stated partial:** §U4.1
(the mapping consolidation landed; the suggested grep-based enforcement test did not) and §U5.2
(the asterisks landed; the suggested `FieldLabel` `required` prop refactor did not). §U10.3
resolved the internal inconsistency the finding was about but deliberately left the dashboard's
larger stat tiles as their own markup — see its resolution note. Every fix was verified against
`bun run typecheck`, `bun lint`, `bunx prettier --check`, `bun run build`, and the full
`vitest` suite (124/124 passing) before being recorded here.

**A second sweep ran on 2026-09-19** and its findings are appended below under
"Sweep 2026-09-19", continuing the same section numbers without reusing any. It re-checked
every resolved finding here and found none regressed. Its headline: four surfaces render a
failed request as "there is nothing here", which is §U7.1's bug on three screens that landed
after §U7.1 was fixed.

**Severity:** 🔴 bug (shows a user something false, or blocks them) · 🟠 inconsistency / latent
risk · 🟡 hygiene · 📄 doc.

**Numbering:** `U1`–`U12`, matching the audit categories. These never collide with
[`audit-findings.md`](audit-findings.md)'s `§1`–`§9`, and are permanent identifiers — new
findings append, existing ones are never renumbered.

**Scope note on `components/ui/`.** That directory is shadcn-CLI-managed
(`design-system.md` §1). Its generated source legitimately contains `dark:` variants,
`rounded-[calc(…)]` arbitrary values, `bg-black/10` overlays and off-scale paddings, so it is
excluded from every token, `dark:`, arbitrary-value and spacing check below. Auditing it
produced ~40 hits, all of them correct. **Application code is clean on all four of those axes**
— see the verified-correct notes.

---

## Top priorities

All nine — ✅ RESOLVED 2026-09-13. Kept in original form, as a record of what the sweep found;
see each linked section for what changed and where.

1. **A failed request tells the user their data does not exist.** Four screens treat "the
   request errored" and "there is nothing here" as the same state, so a backend outage renders
   as "No projects yet — Add a repository". → §U7.1
2. **Three detail screens report every failure as "Not found".** A network blip on a
   conversation renders "That conversation does not exist", which reads as deleted. → §U7.2
3. **The QA Checklist and Mock Data chats silently drop the grounding warnings.** The data is
   on the wire and parsed; nothing renders it. The shared checklist — the artifact the whole
   instance tests against — is the one surface where an uncited or invented answer arrives with
   no warning at all. → §U8.1
4. **Deleting a mock-data record happens on a single click**, with no confirmation and no
   toast. It is the only destructive action in the app that does not confirm. → §U5.1
5. **Error banners are built two different ways**, and the seven that hand-roll the colour
   leave the message text in muted grey instead of red. The same event — a background job
   failed — looks different on `/projects/[id]` than on `/checklist/[moduleId]`. → §U6.1, §U6.2
6. **Five screens hand-copy `PageHeader`'s markup** instead of importing it. → §U2.1
7. **The three list screens implement the same empty state three different ways**, and one of
   them re-implements list-parameter handling from scratch. → §U3.1, §U3.2
8. **Eight different "there is nothing here" treatments** and **four different ways to colour a
   badge**. → §U2.2, §U4.1 (partial — see its resolution note)
9. **`docs/design.md` states the wrong radius for cards and dialogs**, and documents four
   tokens nothing uses. → §U12.1, §U1.2

---

## §U1 Token and theme discipline

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

### §U1.2 Four tokens are defined, documented, and used by nothing — 🟡 hygiene · CONFIRMED — ✅ RESOLVED 2026-09-13

> Fixed: `info` is now used by `UserRoleBadge` (admin badge) and by the two neutral
> notices this finding named — `PROJECT_NOT_READY` in `preflight-error.tsx` and
> "Re-index running" in `project-detail-screen.tsx`, both now `<Alert variant="info">`.
> `chart-1…5` stay unused and are now marked reserved in `docs/design.md` rather than
> implying current use. `components/ui/alert.tsx` gained `info` and `warning` variants
> alongside `destructive`.

Original finding follows.

**Where:** `frontend/app/globals.css:42-43` (`--info`, `--info-foreground`), `:69-74`
(`--chart-1` … `--chart-5`), `:142-143` and `:164-168`; documented at
[`docs/design.md`](design.md):28 and :37

**What this is.** The design system defines a colour role for every job a surface can have.
Two of those roles have no job. `info` is documented as "neutral notice" and `chart-1…5` as
"retrieval scores, eval results". Each is defined twice in `globals.css` (light and dark),
exported to Tailwind, and listed in the token table as a fact about the file.

**Why this can happen.** `grep` for `bg-info`, `text-info`, `border-info`, `chart-1` and
`chart-2` across `app/`, `components/` and `hooks/` returns **zero matches anywhere**,
including inside `components/ui/`. The two places that actually render a neutral notice —
`components/ask/preflight-error.tsx:87` for `PROJECT_NOT_READY`, and
`app/(app)/projects/[id]/project-detail-screen.tsx:87` for "Re-index running" — use a bare
`<Alert>` with the default `bg-card` variant, so they are visually identical to the *error*
alerts beside them apart from a border colour. The role exists for precisely those two cases
and neither reaches for it. `secondary` is a near-miss: four usages, all inside
`components/ui/`, none in application code.

**What it costs.** Little today — an unused CSS variable costs nothing at runtime. The cost is
to the next person: `docs/design.md`'s token table reads as a description of what the app uses,
and two of its rows describe intentions instead. Someone adding an eval-results chart will
reasonably assume `chart-1…5` were chosen to work together and were checked for contrast in
both themes; nothing has ever rendered them, so that assumption is untested.

**What we should do.** Either use `info` for the two neutral notices named above — which is
what it was defined for, and would also fix the fact that a "still indexing" notice currently
looks like an error — or mark both rows in `docs/design.md` as reserved-and-unused so the table
stays an honest description. `chart-*` is reasonable to keep reserved: `docs/design.md`:37
already ties it to M5 work. Under an hour either way.

---

## §U2 Shared shells, adopted or bypassed

### §U2.1 Five screens hand-copy `PageHeader` instead of importing it — 🟠 CONFIRMED — ✅ RESOLVED 2026-09-13

> Fixed: `PageHeader` gained `titleAddon`, `meta`, and `sticky` props and now covers
> all five call sites — `dashboard-screen.tsx`, `project-detail-screen.tsx`,
> `new-conversation-screen.tsx`, `conversation-screen.tsx` (using `sticky` + `meta`
> for the project-link row), and `module-screen.tsx`'s checklist tab (using
> `titleAddon` for the status badge and staleness badge). The Mock Data tab's `h2`
> sub-header was left as-is — it is a tab heading, not a page header.

Original finding follows.

**Where:** hand-rolled at `app/(app)/dashboard-screen.tsx:35-42`,
`app/(app)/projects/[id]/project-detail-screen.tsx:48-57`,
`app/(app)/ask/new-conversation-screen.tsx:39-45`,
`app/(app)/ask/[conversationId]/conversation-screen.tsx:95-97`, and
`app/(app)/checklist/[moduleId]/module-screen.tsx:137-158`. Imported correctly at
`projects-screen.tsx:31`, `users-screen.tsx:41`, `checklist-screen.tsx:88`. The component is
`components/layout/page-header.tsx`.

**What this is.** Every page in the app opens with a title, an optional description, and an
optional action on the right. `PageHeader` is the component that renders exactly that, in
fifteen lines. Three screens use it. Five reproduce its markup by hand.

**Why this can happen.** The copies are not merely similar, they are character-identical.
`page-header.tsx:12-18` renders
`<div className="mb-6 flex flex-wrap items-start justify-between gap-4">`, an `<h1
className="text-3xl font-semibold tracking-tight">`, and a `<p className="text-muted-foreground
mt-1 text-base">`. `dashboard-screen.tsx:36-41` and `new-conversation-screen.tsx:40-44` write
the same two elements with the same class strings. `project-detail-screen.tsx:48` and
`module-screen.tsx:137` write the same wrapper `div` too, differing only in that they place a
status badge beside the title — something `PageHeader` has no slot for, which is presumably why
the first copy happened.

**What it costs.** Nothing visible today; the copies are faithful. It costs on the next change.
The navbar is `h-16` and `design-system.md` §9 calls that geometry load-bearing; the same logic
applies to the header rhythm. Change `mb-6` to `mb-8` in `PageHeader` and three screens move
while five do not, and the person making that change has no way to know from the file they
edited. The sixth copy is already a variant: `module-screen.tsx:313-315` renders the Mock Data
tab's header as an `<h2 className="text-xl font-semibold tracking-tight">`, so switching tabs
on one screen changes the heading's level and size.

**What we should do.** Give `PageHeader` a `titleSuffix?: React.ReactNode` slot for the badge
cluster that drove the divergence, then replace all five copies. Roughly two hours including
reading each call site. The user confirmed on 2026-09-13 that this is drift rather than a
deliberate workspace-versus-list distinction.

### §U2.2 Eight different "there is nothing here" treatments — 🟠 CONFIRMED — ✅ RESOLVED 2026-09-13

> Fixed: `EmptyState` gained a `size="compact"` mode (no icon, no title, `text-sm`),
> built on the new shared `CenteredMessage` primitive (§U2.3). Applied to
> `conversation-rail.tsx`, both refinement chat panels, and `records-table.tsx`. The
> dashboard's two hand-rolled blocks now render `EmptyState` at the default size with
> a real title, per the recommendation.

Original finding follows.

**Where:** `components/feedback/empty-state.tsx` (the component), plus seven bypasses:
`app/(app)/dashboard-screen.tsx:91-102` and `:138-150`,
`components/ask/conversation-rail.tsx:203-207`,
`components/checklist/chat-panel.tsx:244-247`,
`components/mock-data/chat-panel.tsx:208-211`,
`components/mock-data/records-table.tsx:41-44`, and the `ComboboxEmpty` copy at
`components/ask/project-picker.tsx:65-67` / `conversation-rail.tsx:177-179`

**What this is.** `EmptyState` exists so that, in the words of its own docstring, "an empty list
shows this with the primary action, never a bare 'No results'". It renders a centred icon at
`size-8`, an `<h3 className="text-xl font-semibold">` title, a description, and an optional
action, at `py-12`.

**Why this can happen.** Three list screens use it. Everything else invents its own:

| Surface | Treatment |
| --- | --- |
| `EmptyState` | `py-12`, icon `size-8`, `h3` title, `text-base` body, action |
| Dashboard × 2 | `py-6`, icon `size-8`, **no title**, `text-base` body, action at `mt-3` |
| Conversation rail | bare `<p>` at `text-xs`, **no icon, no title, no action** |
| Both refinement chats | bare `<p>` at `text-sm`, no icon, no title, no action |
| Records table | bare `<p>` at `text-sm`, no icon, no title, no action |
| Combobox | one line of text inside the dropdown |

The dashboard pair is the clearest bypass: it is a full-width card panel with room for the real
component, it already imports an icon and renders an action button, and it simply writes the
markup itself at two-thirds the padding and without a title.

**What it costs.** The rhythm of the app changes depending on which screen happens to be empty,
which is most noticeable on a fresh instance — the state every new operator sees first. A user
landing on the dashboard of an empty instance gets two centred icon-plus-sentence blocks, then
clicks through to `/projects` and gets a taller block with a heading. The narrow surfaces have
a real reason to differ (a 18rem rail cannot afford `py-12`), but nothing records that reason,
so the next narrow surface will invent a ninth treatment.

**What we should do.** Give `EmptyState` a `size?: "default" | "compact"` prop — `compact`
dropping the icon and title and using `text-sm` — and route all seven bypasses through it. The
dashboard pair should take the default. Two to three hours. Note in the component's docstring
that `ComboboxEmpty` is deliberately outside this, since it renders inside a dropdown that
shadcn owns.

### §U2.3 `Forbidden`, `NotFound` and `EmptyState` are three copies of one shell, and their heading levels disagree — 🟠 CONFIRMED — ✅ RESOLVED 2026-09-13

> Fixed: extracted `components/feedback/centered-message.tsx`. `EmptyState`,
> `Forbidden`, and `NotFound` are now thin wrappers over it. The heading-level split
> was already the right one (`h2` for a page-body replacement, `h3` inside a card) and
> is preserved explicitly via the `level` prop rather than left implicit.

Original finding follows.

**Where:** `components/feedback/empty-state.tsx:15-21`,
`components/feedback/forbidden.tsx:8-15`, `components/feedback/not-found.tsx:5-12`

**What this is.** Three components that each render "a centred icon, a heading, and a
paragraph, with lots of vertical room" — the app's full-panel message treatment.

**Why this can happen.** All three share the identical wrapper (`flex flex-col items-center
gap-3 py-12 text-center`), the identical icon size (`size-8`), the identical heading classes
(`text-xl font-semibold`) and the identical body classes (`text-muted-foreground max-w-md
text-base`). The only structural difference is the heading element: `EmptyState` uses `<h3>`
(empty-state.tsx:18) while `Forbidden` and `NotFound` use `<h2>` (forbidden.tsx:11,
not-found.tsx:8).

**What it costs.** The visual output is identical, so nothing looks wrong. What differs is the
document outline a screen reader announces: the same visual role produces a level-2 heading on
a forbidden page and a level-3 heading on an empty list, under an `<h1>` that may or may not be
present (`/settings/users` returns `<Forbidden />` at users-screen.tsx:37 **before** rendering
its `PageHeader`, so on that path the `<h2>` is the page's first and only heading, with no
`<h1>` above it). Three copies also mean a change to the shared treatment has to be made three
times.

**What we should do.** Extract a `CenteredMessage` primitive taking icon, tone, heading level,
title and body; build all three on it. Settle the heading level deliberately — `<h2>` is right
when the component replaces a page body, `<h3>` when it sits inside a card. About an hour.

---

## §U3 The list skeleton

### §U3.1 The three list screens answer "the list is empty" three different ways — 🟠 CONFIRMED — ✅ RESOLVED 2026-09-13

> Fixed: `users-screen.tsx` and `checklist-screen.tsx` now branch their `EmptyState`
> title/description on whether a search is active, matching `projects-screen.tsx`'s
> existing pattern. `checklist-screen.tsx`'s empty-state icon changed from `Plus` to
> `ClipboardCheck`.

Original finding follows.

**Where:** `app/(app)/projects/projects-screen.tsx:49-55`,
`app/(app)/settings/users/users-screen.tsx:59-65`,
`app/(app)/checklist/checklist-screen.tsx:112-118`

**What this is.** All three screens have the same shape: a `PageHeader`, a `ListToolbar`, and a
`Card` holding either an `EmptyState` or a table plus pagination. The empty state has to answer
a question the user cares about: *is this list empty because nothing exists, or because my
filter matched nothing?*

**Why this can happen.** Each screen decided separately:

- **`/projects`** gets it right: `title={params.search ? "No projects match" : "No projects
  yet"}` (projects-screen.tsx:52).
- **`/settings/users`** always says `"No accounts match"` (users-screen.tsx:62), even with no
  search active — and pairs it with the description "Provision an account for a colleague to
  get them started", which is the wording for an empty instance, not a failed filter.
- **`/checklist`** always says `"No modules yet"` (checklist-screen.tsx:116), so searching for a
  module that does not exist reports that no modules exist at all.

The icons diverge too: `/projects` uses `FolderGit2` and `/settings/users` uses `Users` — both
subject icons — while `/checklist` uses `Plus` (checklist-screen.tsx:115), an action icon.

**What it costs.** On `/checklist`, a user who searches "payments" and gets "No modules yet —
Point a module at a path in an indexed repository" has been told their modules are gone. The
fix is to clear the search box, and nothing on screen suggests that. `/settings/users` has the
mirror problem in a rarer direction: an admin on a fresh instance sees "No accounts match" when
nothing was filtered.

**What we should do.** Lift the search-aware title into `EmptyState` itself, or into a tiny
helper both screens call, so the decision is made once. `/checklist` should also switch its icon
to a subject icon (`ClipboardCheck`, which `module-screen.tsx:203` already uses for the
checklist). Under an hour.

### §U3.2 `/checklist` re-implements list-parameter handling instead of using `useListParams` — 🟠 CONFIRMED — ✅ RESOLVED 2026-09-13

> Fixed: `useListParams` gained an `extraParams`/`setParam` extension for a screen
> with its own filter, and a `useChecklistModules` hook was added beside
> `useProjects`/`useUsers`. `checklist-screen.tsx` is rewritten on both, dropping the
> hand-built `URLSearchParams` handlers.

Original finding follows.

**Where:** `app/(app)/checklist/checklist-screen.tsx:34-84`, against
`hooks/use-list-params.ts` as used at `projects-screen.tsx:21-25` and `users-screen.tsx:24-28`

**What this is.** Every list screen has to read `page`, `search` and its filters out of the URL,
write them back on change, and reset the page when a filter changes. `useListParams` is the
hook that does this; two of the three screens call it in five lines.

**Why this can happen.** `checklist-screen.tsx` builds its params object by hand from
`useSearchParams()` (lines 34-39), then writes three near-identical `useCallback` handlers —
`handleSearch` (51-62), `handleProjectChange` (63-74) and `handlePageChange` (75-84) — each
constructing a `URLSearchParams`, setting or deleting one key, deleting `page`, and calling
`router.replace`. That is roughly 45 lines reproducing the hook. It also calls `useQuery`
directly (line 41) rather than going through a resource hook the way `useProjects` and
`useUsers` are used, and reads `isPending` where the other two read `isLoading`.

**What it costs.** Three copies of the reset-page-on-filter-change rule instead of one, in the
screen most likely to grow another filter — `/checklist` already has a project filter that
neither other screen has. A future `useListParams` fix (a debounce change, a scroll-restoration
tweak) reaches two screens out of three. The `isPending` / `isLoading` split is a live
correctness difference, not just naming: they mean different things in TanStack Query, and
`isPending` is true on a disabled query.

**What we should do.** Port `/checklist` onto `useListParams`, extending the hook with the
generic extra-filter slot it will need for `projectId` — `.claude/rules/rag.md`'s note about
`ConversationListQuery` subclassing rather than sitting beside `ListQuery` is the same shape of
problem on the backend, and the frontend hook should take the same lesson. Add a `useChecklistModules`
hook beside `useProjects` / `useUsers`. Half a day.

### §U3.3 The checklist module table is the one list whose timestamps have no hover value — 🟠 CONFIRMED — ✅ RESOLVED 2026-09-13

> Fixed: `module-table.tsx` now imports `formatAbsolute` and sets it as the "Last
> generated" cell's `title`, matching `project-table.tsx` and `user-table.tsx`.

Original finding follows.

**Where:** `components/checklist/module-table.tsx:19` (the import) and `:94-107` (the cell),
against `components/projects/project-table.tsx:16,69` and
`components/users/user-table.tsx:14,52,55`

**What this is.** [`docs/design.md`](design.md) → Lists: "Timestamps are relative with an
absolute `title` (`3 days ago`, hover for the ISO value)." `lib/dates.ts` exports the pair that
implements it — `formatRelative` for the text and `formatAbsolute` for the `title`.

**Why this can happen.** `module-table.tsx:19` imports only `formatRelative`. `formatAbsolute`
is never imported, and line 97 renders `{formatRelative(module.lastGeneratedAt)}` with no
`title` attribute on the cell. Both other tables put `title={formatAbsolute(...)}` on the
`TableCell`.

**What it costs.** "Last generated: 3 days ago" is exactly the column where an exact time
matters, because the question a reviewer is actually asking is whether the generation predates
a specific commit or reindex. On `/projects` and `/settings/users` they can hover for the ISO
value. On `/checklist` they cannot, and nothing indicates the affordance is missing on this
table alone.

**What we should do.** Import `formatAbsolute` and add `title={formatAbsolute(module.lastGeneratedAt)}`
to the cell at line 94. Ten minutes. Worth adding a lint rule or a test that asserts every
`formatRelative` call site has a sibling `formatAbsolute` — this is the second time the pair has
to be used together and the first time it was missed.

---

## §U4 Status and semantic colour

### §U4.1 Badge colour is decided four different ways — 🟠 CONFIRMED — ✅ RESOLVED 2026-09-13

> Fixed: the checklist module status mapping moved from
> `module-status-badge.tsx` into `lib/status.ts` beside the project one, so both status
> domains are named in one file. The user role badge is now `UserRoleBadge`
> (`components/users/user-role-badge.tsx`), using the `info` token instead of an
> inline `bg-primary` class. The suggested grep-based enforcement test was not added —
> `staleness-badge.tsx` and the new `UserRoleBadge` are legitimate non-status `<Badge>`
> call sites the grep would also have to special-case, and getting that carve-out
> right felt like a separate, deliberate decision rather than a mechanical fix.

Original finding follows.

**Where:** `lib/status.ts` + `components/feedback/status-badge.tsx` (the intended path),
`components/checklist/module-status-badge.tsx` (a second mapping, in the component layer),
`components/users/user-table.tsx:47-50` (inline classes), and
`components/checklist/staleness-badge.tsx:14` (variant plus override classes)

**What this is.** `design-system.md` §5: "Status colour is semantic and mapped in one place …
Never pick a colour per component — a badge, a table row, and a detail header showing the same
state must agree." `StatusTone` (`lib/status.ts:8`) is the vocabulary and `StatusBadge`
(`status-badge.tsx:17`) is the single renderer that turns a tone into classes.

**Why this can happen.** Four idioms coexist:

1. **Through the mapping** — `ProjectStatusBadge` (status-badge.tsx:30) resolves a
   `ProjectStatus` via `statusTone`/`statusLabel`. Correct.
2. **A second mapping, in a component** — `ChecklistModuleStatusBadge`
   (module-status-badge.tsx:5-21) declares its own `LABELS` and `TONES` records for
   `ChecklistModuleStatus`, then renders through `StatusBadge`. Structurally correct and well
   reasoned in its docstring, but the mapping lives in `components/` while the project mapping
   lives in `lib/`.
3. **Inline classes at the call site** — `user-table.tsx:47` renders `<Badge className="bg-primary
   text-primary-foreground">Admin</Badge>`, and line 49 renders `<Badge variant="outline">Member</Badge>`.
   Two adjacent badges in one table cell, one styled by class override and one by the variant API,
   neither going through `StatusTone`.
4. **Variant plus override** — `staleness-badge.tsx:14` renders `<Badge variant="outline"
   className="border-border text-muted-foreground">`.

**What it costs.** No two states currently disagree about a colour — `ready` is `success` in
both mappings — so there is no wrong colour on screen today. The cost is that `design-system.md`
§5's guarantee is not actually enforced by anything. The fourth idiom to be added is the one
that will disagree, and the row it disagrees on will be a status a reviewer acts on. The user
role badge is the concrete near-miss: `bg-primary` for "Admin" means authority is rendered in
the brand colour, which is also the colour of "Review changes" text at `module-table.tsx:72` and
of every primary button.

**What we should do.** Move `ChecklistModuleStatusBadge`'s mapping into `lib/status.ts` beside
the project one, so `lib/status.ts` is provably the only module naming a tone. Add a
`role`/`neutral` tone for the user badge and route it through `StatusBadge`. Add a test that
greps for `<Badge` outside `components/ui/` and `components/feedback/status-badge.tsx` and
fails — the same shape of grep-backed guarantee `docs/PRD.md` §7 uses for read scoping. Half a
day.

### §U4.2 A module's "needs review" state is signalled twice in one cell, once as bare coloured text — 🟡 CONFIRMED — ✅ RESOLVED 2026-09-13

> Fixed: the second "Review changes" line in `module-table.tsx` is now a
> `StatusBadge` with the same `warning` tone `review` uses, instead of bare
> `text-primary` text — chosen over deleting it outright because a chat-originated
> change set can be pending without the module status itself having moved to
> `review`.

Original finding follows.

**Where:** `components/checklist/module-table.tsx:68-75`

**What this is.** The Status column of the module list renders the module's status badge and,
beneath it, a second line reading "Review changes" when a change set is pending.

**Why this can happen.** `ChecklistModuleStatusBadge` already maps `review` to the `warning`
tone, and its docstring explains exactly why: "A module with a proposal waiting is not finished,
and showing it green would say it was. `review` is the state the whole feature exists to make
visible." Line 72 then adds `<div className="text-primary text-xs">Review changes</div>` — the
same fact again, in a different colour, as unbadged text. [`docs/design.md`](design.md) → Lists
says status renders as a `Badge` with the semantic colour.

**What it costs.** Two signals for one state, in two different colours (`warning` on the badge,
`primary` on the text), in one table cell. A reader has to work out whether they mean different
things. They do not.

**What we should do.** Drop the second line, or — if the intent was to distinguish "a change set
is pending" from the module's own status, which are separately tracked — render it as a second
`StatusBadge` with an explicit tone so the two agree about what colour "needs a human" is.
Twenty minutes.

### §U4.3 `text-destructive` and `text-danger` are both used in hand-written code — 🟡 CONFIRMED — ✅ RESOLVED 2026-09-13

> Fixed: the one `text-destructive` usage in `module-table.tsx` is now `text-danger`.

Original finding follows.

**Where:** `components/checklist/module-table.tsx:82` uses `text-destructive`; fourteen
application files use `text-danger`

**What this is.** `globals.css:45-48` defines `--destructive: var(--danger)` with a comment
saying exactly why: "shadcn calls the danger role 'destructive'. Both map to one value so a
CLI-generated component and a hand-written one cannot diverge." The alias exists so generated
code can say `destructive` and hand-written code can say `danger`.

**Why this can happen.** `module-table.tsx` is hand-written and says `destructive`. It renders
identically, since the tokens resolve to the same value.

**What it costs.** Nothing visual. It costs the grep: someone auditing "where does this app show
danger colour" and searching `text-danger` gets fourteen files and misses this one.

**What we should do.** Change line 82 to `text-danger`. Two minutes. Consider a lint rule
banning `destructive` utilities outside `components/ui/`.

---

## §U5 Forms, dialogs and confirmations

### §U5.1 Deleting a mock-data record is the one destructive action with no confirmation — 🟠 CONFIRMED — ✅ RESOLVED 2026-09-13

> Fixed: `records-table.tsx`'s delete button now opens a `ConfirmDialog` and fires
> success/error toasts, matching every other destructive action in the app.

Original finding follows.

**Where:** `components/mock-data/records-table.tsx:63-73`, against
`components/projects/project-row-actions.tsx:130-160` (delete project),
`components/checklist/module-row-actions.tsx` (delete module),
`components/users/user-row-actions.tsx:59-76` (deactivate user),
`components/ask/conversation-rail.tsx:53-70` (delete conversation), and
`app/(app)/checklist/[moduleId]/module-screen.tsx:279-303` (clear results)

**What this is.** [`docs/design.md`](design.md) → Feedback maps "Destructive confirmation" to
`ConfirmDialog`, with no carve-out. Five destructive actions in the app follow it. The sixth
does not.

**Why this can happen.** `records-table.tsx:64-72` renders an icon-only ghost button whose
`onClick` calls `deleteRecord.mutate(record.id)` directly. There is no `ConfirmDialog`, no
`onSuccess` toast, and no `onError` handler. The button sits in the last column of a table whose
other columns are dynamic — `columnsFor` (line 19) derives them from whatever fields the
generated records happen to carry — so the trash button's horizontal position moves depending on
the dataset.

**What it costs.** One misclick deletes a record with no warning, no acknowledgement that it
happened, and no undo. Because there is no toast on either path, a delete that *fails* is also
completely silent: the row stays, nothing is said, and the user's reasonable conclusion is that
the button is broken. In a table whose column count varies by dataset, a trash button that moves
between views is exactly the kind of target that gets hit by accident.

**What we should do.** Wrap it in `ConfirmDialog` like the other five, and add the success and
error toasts every other mutation in the app fires. The user confirmed on 2026-09-13 that this
is drift, not a deliberate low-friction choice. About an hour.

### §U5.2 Required fields are unmarked on the login screen — 🟠 CONFIRMED — ✅ RESOLVED 2026-09-13

> Fixed: both labels on `login-screen.tsx` now carry the trailing `text-danger`
> asterisk. The suggested `FieldLabel` `required` prop (to stop the asterisk markup
> being copy-pasted at every call site) was not built — it touches five existing call
> sites for a purely cosmetic win and felt like its own change.

Original finding follows.

**Where:** `app/(auth)/login/login-screen.tsx:117` and `:131`, against
`components/projects/create-project-dialog.tsx:71`,
`components/users/create-user-dialog.tsx:50,65`,
`components/users/change-password-fields.tsx:31`, and
`components/form/password-field.tsx:63`

**What this is.** [`docs/design.md`](design.md) → Forms: "Required fields mark the label with a
trailing asterisk in `text-danger`." Every required field elsewhere in the app does this,
including the one rendered inside `PasswordField` itself.

**Why this can happen.** Login's two labels are plain: `<FieldLabel htmlFor="email">Email</FieldLabel>`
and `<FieldLabel htmlFor="password">Password</FieldLabel>`. Both fields *are* required — lines
41-44 reject empty values before submitting.

**What it costs.** Small on its own: nobody is confused about whether a sign-in form needs a
password. It matters because login is the first screen every user sees, and it teaches them that
this app does not mark required fields — a rule the very next screen (`/change-password`, via
`ChangePasswordFields:31` and `PasswordField:63`) breaks in both directions.

**What we should do.** Add the asterisk spans to both labels. Ten minutes. Better: give
`FieldLabel` a `required` prop so the asterisk markup exists once rather than in five call sites
— it is currently copy-pasted as `<span className="text-danger">*</span>` at every one.

### §U5.3 The auth flow's card doubles in width between its two screens — 🟠 CONFIRMED — ✅ RESOLVED 2026-09-13

> Fixed: `FormPage` gained a `width` prop (`"default" | "narrow"`), and
> `change-password-screen.tsx` now passes `width="narrow"` so the card no longer
> doubles in size right after login.

Original finding follows.

**Where:** `app/(auth)/login/login-screen.tsx:79` (`<Card className="w-full max-w-sm">`) and
`app/(auth)/change-password/change-password-screen.tsx:54` rendering
`components/form/form-page.tsx:29` (`max-w-3xl`), both inside
`app/(auth)/layout.tsx:4`

**What this is.** A newly provisioned user signs in, and because `must_change_password` is set
(`app/(app)/layout.tsx:24`), is redirected straight to `/change-password`. Those two screens are
consecutive and share the shell-less centred auth layout.

**Why this can happen.** Login hand-builds a `Card` capped at `max-w-sm` (24rem) with a
full-width submit button (`login-screen.tsx:146`). Change-password uses `FormPage`, which is
capped at `max-w-3xl` (48rem) with a right-aligned submit (`form-page.tsx:52-57`). `FormPage`'s
width is chosen for a form sitting on a full app page with the sidebar beside it; on the auth
background there is no sidebar to balance it.

**What it costs.** The card visibly doubles in width, and the submit button jumps from
full-width-centred to right-aligned, between two screens a user sees back to back within
seconds. It is the app's first impression of whether its layout is deliberate.

**What we should do.** Give `FormPage` a `width?: "sm" | "md" | "lg"` prop mirroring
`FormDialog`'s `SIZES` map (form-dialog.tsx:31), and have `/change-password` pass the narrow
one. The user confirmed on 2026-09-13 that narrowing change-password is the right direction.
About an hour.

### §U5.4 `ConfirmDialog` hardcodes a width class that `forms.md` §3 bans — 🟡 CONFIRMED — ✅ RESOLVED 2026-09-13

> Fixed: `FormDialog` now exports its `SIZES` map, and `ConfirmDialog` uses
> `SIZES.sm` instead of a hardcoded `sm:max-w-md` class.

Original finding follows.

**Where:** `components/form/confirm-dialog.tsx:38`, against `components/form/form-dialog.tsx:31`

**What this is.** `forms.md` §3: "Dialog width is a size, never a class … Pick a size; do not
pass a `max-w-*` class." `FormDialog` implements this with a `SIZES` map.

**Why this can happen.** `ConfirmDialog` writes `<DialogContent className="sm:max-w-md">`
directly. It happens to equal `SIZES.sm`, so the two shells currently agree by coincidence
rather than by construction.

**What it costs.** Dialog width is now defined in two places. Retune `SIZES.sm` and confirmation
dialogs silently stay where they were, so a row of dialogs that used to match stops matching.

**What we should do.** Export `SIZES` from `form-dialog.tsx` and have `ConfirmDialog` use
`SIZES.sm`. Fifteen minutes.

### §U5.5 A `SelectTrigger` in the result cell keeps its default `w-fit` — 🟠 CONFIRMED — ✅ RESOLVED 2026-09-13

> Fixed: `result-cell.tsx`'s status `SelectTrigger` now takes `className="w-full"`.

Original finding follows.

**Where:** `components/checklist/result-cell.tsx:83`, against
`components/checklist/module-filters.tsx:64`, `components/checklist/item-filters.tsx:79,113,141`
and `components/mock-data/generate-control.tsx:53`

**What this is.** `components/ui/select.tsx:44` gives `SelectTrigger` a `w-fit` base, so a
trigger collapses to the width of its shortest label unless told otherwise. Every other select in
the app passes an explicit width — `module-filters.tsx:54-56` even carries a comment explaining
why: "`SelectTrigger` is `w-fit` by default, which collapses it to the width of the shortest
label."

**Why this can happen.** `result-cell.tsx:83` renders `<SelectTrigger id={...}>` with no
`className`. It sits in a `flex flex-col gap-3` (line 65) alongside a full-width `Textarea` and a
full-width Save button.

**What it costs.** In the status column of the checklist grid — the control a tester uses on
every row — the Status select is visibly narrower than the Current-result box directly above it
and the Save button directly below, and its width changes as the selection changes, because
"Pass" and "Blocked — could not run" (result-cell.tsx:25) are very different lengths. The column
reflows as a tester works down it.

**What we should do.** Add `className="w-full"` at line 83. Five minutes. The comment at
`module-filters.tsx:54-56` documents this trap already; consider moving that note into
`components/ui/select.tsx`'s call sites or defaulting the trigger to `w-full` in a wrapper.

### §U5.6 One pending-button idiom out of six is a text swap rather than a spinner — 🟠 CONFIRMED — ✅ RESOLVED 2026-09-13

> Fixed: `result-cell.tsx`'s Save button now shows the shared `Loader2` spinner with a
> stable label, matching every other pending submit in the app.

Original finding follows.

**Where:** `components/checklist/result-cell.tsx:109`, against `form-dialog.tsx:70`,
`form-page.tsx:54`, `confirm-dialog.tsx:53` and `login-screen.tsx:147`

**What this is.** [`docs/design.md`](design.md) → Forms: "A pending submit disables the button
and shows a spinner inside it — never a full-page overlay." Four shells implement exactly that
with `<Loader2 className="size-4 animate-spin" />`.

**Why this can happen.** `result-cell.tsx:109` renders `{isSaving ? "Saving…" : "Save result"}` —
the label is replaced by a different string and no spinner appears.

**What it costs.** The button's width changes as it swaps between two different strings, nudging
the layout of a cell a tester is actively working in. More practically, it is the one pending
state in the app that does not look like the others, on the control used most often.

**What we should do.** Use the `Loader2` pattern with a stable label. Fifteen minutes.

---

## §U6 Error surfaces and the copy that carries them

### §U6.1 Error banners are built two different ways, and the hand-rolled recipe leaves the message grey — 🟠 CONFIRMED — ✅ RESOLVED 2026-09-13

> Fixed: all seven hand-rolled sites now use `variant="destructive"` —
> `form-error.tsx`, `conversation-screen.tsx`, `preflight-error.tsx` (three of its four
> blocks; the fourth was the `PROJECT_NOT_READY` neutral notice, fixed under §U1.2 with
> `variant="info"`), and both refinement chat panels. `components/ui/alert.tsx`'s
> `destructive` variant gained a matching `border-danger`, so the variant alone now
> produces the fully-coloured border+title+description look these sites were
> reaching for by hand.

Original finding follows.

**Where:** using the variant correctly — `components/checklist/chat-panel.tsx:235,269`,
`components/mock-data/chat-panel.tsx:199,232`,
`app/(app)/checklist/[moduleId]/module-screen.tsx:254,382`. Hand-rolling the colour —
`components/form/form-error.tsx:17`,
`app/(app)/projects/[id]/project-detail-screen.tsx:96-99`,
`app/(app)/ask/[conversationId]/conversation-screen.tsx:156-158`,
`app/(app)/ask/[conversationId]/preflight-error.tsx:36-37,50-51,97-98`,
`components/checklist/chat-panel.tsx:260-261`, `components/mock-data/chat-panel.tsx:223-224`.
The component is `components/ui/alert.tsx:6-20`.

**What this is.** `Alert` ships a `destructive` variant whose class list is
`"bg-card text-destructive *:data-[slot=alert-description]:text-destructive/90"`
(alert.tsx:12-13). The third part of that is the load-bearing one: it reaches into the
description child and colours it.

**Why this can happen.** Seven call sites write `className="border-danger"` on the `Alert` and
`className="text-danger"` on the `AlertTitle` instead of passing `variant="destructive"`. That
colours the border and the title — but `AlertDescription` sets `text-muted-foreground` on
itself (alert.tsx:58), and a class on the element beats a colour inherited from its parent. So
in all seven, **the actual error message renders in muted grey inside a red-bordered box.**
`form-error.tsx:17` is the worst case because it has no `AlertTitle` at all, so *nothing* in that
banner is red except the border.

The split runs inside single files: `chat-panel.tsx` uses `variant="destructive"` at line 235
for the load error and at line 269 for the pre-flight error, but hand-rolls the colour at line
260 for the stream error — three error banners in one component, two recipes.

**What it costs.** The form-level error banner is the app's primary channel for "the server
rejected this and named no field" — `LAST_ADMIN` on user deactivation
(`user-row-actions.tsx:66`), `INVALID_CREDENTIALS` on login (`login-screen.tsx:113`), every
`VECTOR_STORE_UNAVAILABLE`. In every one of those, the sentence the user needs to read is the
same grey as ordinary helper text. The message is present and announced (`role="alert"` is set
by `Alert` itself at alert.tsx:30), so this is a legibility and hierarchy failure rather than a
disappearance — but it undercuts the one visual signal the banner exists to send.

**What we should do.** Replace all seven with `variant="destructive"`, and delete the redundant
`role="alert"` at `form-error.tsx:17`. Give `form-error.tsx` an `AlertTitle` so it matches the
others. Then add a lint rule or test banning `border-danger` on an `Alert`. Two to three hours
including a visual check of each site in both themes.

### §U6.2 The same event — a background job failed — is styled differently on two screens — 🟠 CONFIRMED — ✅ RESOLVED 2026-09-13

> Fixed: extracted `components/feedback/job-failure-alert.tsx`, used by
> `project-detail-screen.tsx` and both of `module-screen.tsx`'s failure banners. All
> three now render `font-mono` — settling the question the finding raised in favour of
> both legitimately containing a path.

Original finding follows.

**Where:** `app/(app)/projects/[id]/project-detail-screen.tsx:95-103` versus
`app/(app)/checklist/[moduleId]/module-screen.tsx:253-258` and `:381-386`

**What this is.** Three screens report the identical thing: a background job failed, and here is
the backend's already-scrubbed error message.

**Why this can happen.** The module screen writes `<Alert variant="destructive">` with a plain
`AlertTitle` and `AlertDescription`. The project detail screen writes `<Alert
className="border-danger">`, `<AlertTitle className="text-danger">`, and an
`AlertDescription className="font-mono text-sm"`. So the same class of message is red-titled with
a mono body on one screen and destructive-variant with a proportional body on another.

**What it costs.** A user who has seen an indexing failure on `/projects/[id]` and then meets a
generation failure on `/checklist/[moduleId]` gets no visual cue that these are the same kind of
event from the same kind of worker. The `font-mono` difference is the more defensible half — a
clone error genuinely contains paths — but it is applied on one screen and not the other with
nothing recording why.

**What we should do.** Settle on one treatment for "a background job failed" and extract it as a
`JobFailureAlert` taking the scrubbed message, used by all three. Decide the `font-mono` question
once: both messages come from the same scrubbing path, so both should render the same way. About
an hour, and it subsumes part of §U6.1.

### §U6.3 `GroundingNotice` is a third notice language — 🟡 CONFIRMED — ✅ RESOLVED 2026-09-13

> Fixed: `GroundingNotice` is rewritten on `Alert`'s new `warning` variant instead of
> a hand-rolled tinted div, per the finding's first option.

Original finding follows.

**Where:** `components/ask/grounding-notice.tsx:25`, against `components/ui/alert.tsx:7`

**What this is.** Grounding warnings are the app's most important advisory surface — per
`.claude/rules/rag.md`, they exist to make model dishonesty visible, and "a check whose result
nothing can see is not a check."

**Why this can happen.** It does not use `Alert`. It hand-rolls `<div className="border-warning
bg-warning/10 mt-4 rounded-md border p-3">` with its own icon-and-list layout. That makes it the
only notice in the app with a **tinted background** — every `Alert` is `bg-card` with a coloured
border — and it uses `rounded-md` where `Alert` uses `rounded-lg` (alert.tsx:7).

**What it costs.** Three visual languages for "pay attention to this": tinted-background div
(grounding), card-with-coloured-border (danger alerts), plain card (neutral alerts). The
grounding notice's distinctness is arguably a feature — it *should* stand out — but it is
undocumented, so the next advisory surface has three precedents to choose between.

**What we should do.** Either add a `warning` variant to `components/ui/alert.tsx` and use it, or
record in [`docs/design.md`](design.md) → Feedback that grounding warnings deliberately use a
tinted treatment and why. Half an hour either way; the decision matters more than the code.

### §U6.4 Success-toast voice is split — 🟡 CONFIRMED — ✅ RESOLVED 2026-09-13

> Fixed, per the user's 2026-09-13 decision for the terse house style: the three
> multi-sentence toasts — `generate-control.tsx`, `module-screen.tsx`'s Generate
> button, and `create-module-dialog.tsx` — are now "Generation started" and "Module
> created".

Original finding follows.

**Where:** terse — `project-row-actions.tsx:122,141`, `create-project-dialog.tsx:48`,
`create-user-dialog.tsx:30`, `edit-user-dialog.tsx:40`, `reset-password-dialog.tsx:30`,
`change-password-dialog.tsx:29`, `change-password-screen.tsx:27`, `user-row-actions.tsx:71`,
`conversation-rail.tsx:64`, `item-grid.tsx:153,326`, both change-set panels' "Changes applied".
Explanatory — `generate-control.tsx:37`, `module-screen.tsx:182`,
`create-module-dialog.tsx:73`.

**What this is.** [`docs/design.md`](design.md) → Feedback: a successful mutation gets a
`sonner` toast, "brief, no title".

**Why this can happen.** Most are terse object phrases with no trailing period — "Password
changed", "Changes applied", "Re-index started", `${project.name} deleted`. Three are
two-sentence explanations with periods: "Generating. The proposals appear here when it
finishes." and "Module created. Generating its checklist…". All three of the long ones are
generation-related, which suggests they were written together and to a different instinct.

**What it costs.** Minor and purely tonal, but it is the most-seen copy in the app and the place
an assembled-by-committee feel shows first.

**What we should do.** The user settled the house style on 2026-09-13: **terse, no trailing
period.** Rewrite the three long ones — "Generation started" — and move the explanation to the
screen that shows the status, which is where the user will look anyway. Half an hour. Note that
error toasts legitimately stay as sentences: `project-row-actions.tsx:149-153` pairs a message
with a `description`, which is the right shape for a failure that needs a next step.

---

## §U7 The loading / empty / error triad

### §U7.1 A failed request renders as "there is nothing here" — 🔴 CONFIRMED — ✅ RESOLVED 2026-09-13

> Fixed: extracted `components/feedback/list-error.tsx`. All five sites —
> `projects-screen.tsx`, `users-screen.tsx`, `checklist-screen.tsx`, and both of
> `dashboard-screen.tsx`'s panels — now check `isError` ahead of the empty-state
> branch and render it with a retry wired to the query's own `refetch`.

Original finding follows.

**Where:** `app/(app)/projects/projects-screen.tsx:49`,
`app/(app)/settings/users/users-screen.tsx:59`,
`app/(app)/checklist/checklist-screen.tsx:112`, and
`app/(app)/dashboard-screen.tsx:90` and `:137`

**What this is.** Each of these screens reads a list with TanStack Query and decides what to
render. A query has three outcomes that matter: still loading, succeeded, failed. These five
call sites collapse the last two into one.

**Why this can happen.** The pattern is identical everywhere:

```tsx
const projects = query.data?.items ?? [];        // [] when the request FAILED
…
{!query.isLoading && projects.length === 0 ? <EmptyState … /> : <Table … />}
```

When the request fails, `query.data` is `undefined`, so `?? []` yields an empty array;
`isLoading` is false because the query settled. The empty branch wins. `query.isError` is never
consulted on any of the five. (The dashboard's version at lines 90 and 137 is the same shape
via `(projects.data?.items.length ?? 0) === 0`.)

**What it costs.** With the backend down, Qdrant unreachable, or the session refresh failing,
`/projects` renders: **"No projects yet — Add a repository and AskRepo will clone and index it"**,
with an "Add project" button. The user is being told, in confident product copy, that the
instance holds no repositories. The correct reading — "we could not reach the server" — is
nowhere on screen. On `/settings/users` an admin is told there are no accounts, which on an
instance that seeds bootstrap admins (`docs/PRD.md` §3) is never true. Worse, the offered action
is to create more: a user who follows the empty state's instruction and clicks "Add project"
gets a dialog whose submit will also fail, against a list they now believe is empty.

**What we should do.** Add an error branch ahead of the empty branch on all five, rendering an
`Alert` with the message and a retry. `Forbidden` on `403`, `NotFound` on `404`, an `Alert`
otherwise — the same ladder `project-detail-screen.tsx:30-38` reaches for. Best done as a small
`<QueryBoundary query={…} empty={…}>` wrapper so the ordering is decided once and the next list
screen cannot get it wrong. Half a day including the four other screens.

### §U7.2 Three detail screens report every failure as "Not found" — 🔴 CONFIRMED — ✅ RESOLVED 2026-09-13

> Fixed: extracted `components/feedback/detail-error.tsx`, branching `404` →
> `NotFound`, `403` → `Forbidden`, anything else → a destructive `Alert` with retry.
> Used by `project-detail-screen.tsx`, `module-screen.tsx`, and
> `conversation-screen.tsx` (which previously had no status check on this path at
> all).

Original finding follows.

**Where:** `app/(app)/ask/[conversationId]/conversation-screen.tsx:62-66`,
`app/(app)/projects/[id]/project-detail-screen.tsx:30-38`,
`app/(app)/checklist/[moduleId]/module-screen.tsx:109-117`

**What this is.** Each detail screen fetches one resource and must distinguish "this does not
exist" from "we could not ask". `response-api.md` and `.claude/rules/rag.md` are precise about
the backend's side: a conversation miss is always `404`, never `403`, and project existence is
deliberately public so its miss is also `404`.

**Why this can happen.** The screens correctly conclude that a *miss* is a `404` — and then
treat every other failure as one too. `project-detail-screen.tsx:33-38` special-cases status
`404` with a tailored message, then falls through to `return <NotFound message={(query.error as
Error).message} />` for everything else. `module-screen.tsx:111-116` does the same.
`conversation-screen.tsx:62-66` does not even check the status: any error at all returns
`<NotFound message="That conversation does not exist." />`.

A `500`, a `503 VECTOR_STORE_UNAVAILABLE`, a dropped connection, or a refresh failure all land
in that branch.

**What it costs.** `NotFound` renders "Not found" above "It may have been deleted, or it may
never have existed" (not-found.tsx:8-11). On the conversation screen the message is hardcoded to
"That conversation does not exist." A user whose wifi drops mid-navigation is told their
conversation was deleted — and conversations are private and unrecoverable
(`conversation-rail.tsx:57`: "Only you can see it, and it cannot be recovered"), so that is a
believable and alarming claim. The user's rational response is to stop looking for it. Reloading
would have worked.

**What we should do.** Branch on the status: `404` → `NotFound`, `403` → `Forbidden`, anything
else → an `Alert` with the real message and a retry button. `conversation-screen.tsx` needs the
status check added, not just the branch. Two to three hours across the three screens, and it
shares the `QueryBoundary` helper from §U7.1.

### §U7.3 The dashboard uses two loading idioms on one screen — 🟡 CONFIRMED — ✅ RESOLVED 2026-09-13

> Fixed: the two stat tiles in `dashboard-screen.tsx` now render a sized `Skeleton`
> instead of an em-dash while loading.

Original finding follows.

**Where:** `app/(app)/dashboard-screen.tsx:56` and `:66` (an em-dash) versus `:87-89` and
`:134-136` (`Skeleton`)

**What this is.** [`docs/design.md`](design.md) → Lists: "Loading shows `Skeleton` rows matching
the real column count, not a spinner — the layout must not jump when data arrives."

**Why this can happen.** The two stat tiles render `{projects.isLoading ? "—" : totalCount}`,
substituting an em-dash for the number. The two list panels below them render `Skeleton` blocks.
So the top half of the dashboard and the bottom half load differently.

**What it costs.** The em-dash is also the app's "this value is null" glyph — `project-table.tsx:61,67`
and `project-stats.tsx:18,19,26,37` all use "—" for a genuinely absent value. On the dashboard it
means "not loaded yet", so the same glyph carries two meanings, and a stat tile that is loading
is indistinguishable from one whose count is unknown.

**What we should do.** Use a `Skeleton` sized to the number in both tiles. Twenty minutes.

---

## §U8 The three streaming surfaces

### §U8.1 Two of the three streaming surfaces silently drop the grounding warnings — 🔴 CONFIRMED — ✅ RESOLVED 2026-09-13

> Fixed: `groundingWarnings` is now read from `result.done` in both
> `lib/checklist/stream.ts` and `lib/mock-data/stream.ts`'s consumers' callers,
> carried in both chat panels' `TurnState`, and rendered via `GroundingNotice` exactly
> as `conversation-screen.tsx` already did — unconditional on `reconciled`, for the
> same reason.

Original finding follows.

**Where:** rendered at `app/(app)/ask/[conversationId]/conversation-screen.tsx:146` via
`hooks/use-ask-stream.ts:29,50,79`. Absent from `components/checklist/chat-panel.tsx` and
`components/mock-data/chat-panel.tsx`. The payload is `lib/api/types.ts:197`; the parsers are
`lib/checklist/stream.ts:62-63` and `lib/mock-data/stream.ts:56-57`.

**What this is.** `app/rag/grounding.py` compares each finished answer against what was actually
retrieved and emits warnings — `unknown_paths` (the answer named a file no excerpt contains),
`uncited_answer` (excerpts were supplied and no `[n]` label was used), `weak_evidence`,
`no_context`. `.claude/rules/rag.md` is blunt about their purpose: "None of this makes the model
honest — it makes dishonesty **visible**. A check whose result nothing can see is not a check."
`components/ask/grounding-notice.tsx` is the component that shows them.

**Why this can happen.** This is not a plumbing gap — the data reaches both panels. `DoneEventPayload`
carries `groundingWarnings: string[]` (types.ts:197). Both `consumeChecklistStream` and
`consumeMockDataStream` assign the whole payload into `result.done` (stream.ts:63 and :57
respectively). Both panels then read exactly one field off it:

```tsx
} else if (result.done) {
  current = { ...current, isStreaming: false, citedIndexes: result.done.citedIndexes };
}
```

`result.done.groundingWarnings` is sitting right there, in scope, and is never read. Neither
panel imports `GroundingNotice`. A grep for `groundingWarnings` across the whole frontend returns
five hits, all on the Ask path.

**What it costs.** The Ask screen is private — one person reads that answer and the warning is
shown to them. The QA Checklist is the opposite: `docs/PRD.md` §4.3 publishes it to the whole
instance, and a change set is a document other people are relied on to test against. So the
surface where an uncited or path-inventing proposal does the most damage is the surface that
shows no warning at all. A reviewer ticking operations in the change-set drawer has no signal
that the turn which produced them cited nothing, or named files that were not in the excerpts.
The same applies to mock data, where `docs/PRD.md` §7's success criterion is that "every field
name it proposes actually exists in that module's code".

Nothing errors. The warnings are computed server-side, sent over the wire, parsed into an object,
and dropped on the floor.

**What we should do.** Add `groundingWarnings` to both panels' `TurnState`, populate it from
`result.done` alongside `citedIndexes`, and render `<GroundingNotice warnings={…} />` beside the
answer exactly as `conversation-screen.tsx:146` does. Two small, near-identical changes — roughly
an hour including tests. **Mind the `intent` carve-out** while doing it: per `.claude/rules/rag.md`,
`conversational` and `out_of_scope` turns carry empty warnings deliberately, and `intent`
(types.ts:198, currently unread anywhere) is what explains that.

### §U8.2 Only the Ask screen tells the user what the model is doing — 🟠 CONFIRMED — ✅ RESOLVED 2026-09-13

> Fixed: extracted `lib/ask/phase-labels.ts`'s `PHASE_LABELS`, now imported by
> `conversation-screen.tsx` and both refinement chat panels. Both `lib/checklist/stream.ts`
> and `lib/mock-data/stream.ts` gained an `onPhase` handler reading the `status`
> event that was previously parsed and silently discarded.

Original finding follows.

**Where:** `app/(app)/ask/[conversationId]/conversation-screen.tsx:23-29` (the labels) and
`:125-129` (the render); absent from `components/checklist/chat-panel.tsx:250-266` and
`components/mock-data/chat-panel.tsx:214-229`

**What this is.** A turn passes through graph phases — classify, retrieve, grade, generate — and
the Ask screen surfaces them: "Understanding the question…", "Searching the codebase…",
"Checking what it found…", "Writing the answer…".

**Why this can happen.** `PHASE_LABELS` and the `state.phase` render live only in
`conversation-screen.tsx`. Neither refinement chat tracks a phase; both go from nothing to the
first token.

**What it costs.** These turns are the slow ones — retrieval plus grading plus generation, and
`docs/PRD.md` §6 records a reduce call taking 22 minutes on CPU. On the Ask screen the user sees
the system working. In the checklist and mock-data drawers they see an empty panel and a disabled
composer. Since `refinement-drawer.tsx:76-82` documents that closing the drawer aborts the
stream, a user who concludes nothing is happening and closes it actively interrupts their own
answer — the UI's silence causes the abort.

**What we should do.** Lift `PHASE_LABELS` into a shared module and have both stream consumers
surface the phase the same way. Two to three hours. This and §U8.1 are the same fix in the same
two files and should land together.

### §U8.3 The two change-set panels have diverged into different review experiences — 🟠 CONFIRMED — ✅ RESOLVED 2026-09-13

> Fixed: extracted `components/change-sets/operation-row.tsx` (`OperationRow` and
> `OperationRationale`). `mock-data/change-set-panel.tsx` now renders its rows through
> the shared `OperationRow` instead of a bespoke `div`, so both panels dim an orphaned
> operation and lay out its checkbox identically. The operation-content renderers stay
> separate, as the finding recommended — a checklist item and a mock record
> genuinely differ.

Original finding follows.

**Where:** `components/checklist/change-set-panel.tsx` (364 lines) versus
`components/mock-data/change-set-panel.tsx` (210 lines)

**What this is.** Both panels do the same job: show a list of proposed operations with their
rationales, let a human tick the ones to accept, and apply or discard. `docs/PRD.md` §4.4
describes mock data as using "the same generate → chat → change-set → apply flow as M4".

**Why this can happen.** The mock-data panel is a reduced fork. A diff shows it dropped
`OperationRow` (the shared checkbox-plus-orphan-dimming row wrapper), dropped the `Badge` import
entirely, dropped the `FIELD_LABELS` map that turns `expectedResult` into "Expected result", and
replaced per-field diffing with `fieldMapText`, which flattens a record to `"key: value, key:
value"`. The checklist panel dims orphaned operations via `OperationRow`'s `orphaned` prop; the
mock-data panel computes `isOrphaned` but has no shared row to express it through.

**What it costs.** A reviewer who has learned to read the checklist's change set — ticking rows,
seeing which are greyed out because their target is gone, reading labelled field diffs — gets a
materially plainer surface on the Mock Data tab for the same task. Both are reached from the same
`RefinementDrawer` on the same screen, two tabs apart, which is the shortest possible distance
between two versions of one interaction.

**What we should do.** Extract `OperationRow` and the orphan treatment into a shared module both
import; keep the operation *content* renderers separate, since a checklist item and a mock record
genuinely differ. That is the split `mock-data/chat-panel.tsx:40-47` already reasons about
correctly for the chat panels. Half a day.

### §U8.4 The checklist change-set panel may reuse a previous change set's tick state — 🟠 SUSPECT — ✅ RESOLVED 2026-09-13

> Fixed defensively: `module-screen.tsx` now passes `key={pendingChangeSet.id}` to
> `ChangeSetPanel`, matching the `key` its mock-data twin already had. The underlying
> question this finding raised — whether the checklist path could actually reach the
> bad state — was not separately settled with a test; the fix removes the risk
> regardless of the answer.

Original finding follows.

**Where:** `app/(app)/checklist/[moduleId]/module-screen.tsx:209-213` (no `key`) versus `:340-345`
(`key={pendingMockDataChangeSet.id}`); the state is seeded at
`components/checklist/change-set-panel.tsx:117-123`

**What this is.** Both panels seed their checkbox map once, in a `useState` lazy initialiser, from
the change set passed in as a prop. A lazy initialiser runs on mount only — if the same component
instance is handed a different change set, the ticks from the previous one survive.

**Why this can happen.** `MockDataChangeSetPanel` is given `key={pendingMockDataChangeSet.id}` at
module-screen.tsx:341, which forces a remount when the change set changes. `ChangeSetPanel` at
line 209 has no `key`. The seeding code is otherwise identical (change-set-panel.tsx:117-123 and
mock-data/change-set-panel.tsx:64-70). `CHANGELOG.md` records `fix(mock-data): key the change-set
panel by its pending change set id` as a real defect that was fixed — on one side only.

**Unverified:** whether the checklist path can actually reach the bad state. Both drawers are
conditionally mounted on a non-null pending change set, and `SheetContent` unmounts its children
on close (refinement-drawer.tsx:76-82), so the ordinary flow — apply, `pendingChangeSetId` goes
null, panel unmounts — appears safe. The risk is a transition where the module-detail query and
the change-sets list query settle in the same commit and `pendingChangeSet` goes from set A
directly to set B with no null render between.

**What would settle it:** a test that renders `ModuleScreen` with a pending change set, then
updates both queries in one act() to a second change set with different operation ids, and
asserts the checkbox map re-seeded. If the mock-data fix had a reproducible trigger, the same
trigger applied to the checklist path answers it directly.

**What we should do.** Add `key={pendingChangeSet.id}` at module-screen.tsx:209 regardless of the
verdict — it costs nothing, it makes the two call sites symmetric, and it removes the question.
Five minutes. Then write the test to establish whether it was load-bearing.

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

---

## §U9 Navigation and route gating

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

### §U9.2 `.claude/rules/navigation.md`'s route list omits a route that exists — 📄 CONFIRMED — ✅ RESOLVED 2026-09-13

> Fixed: added the `/settings` index route to the table in
> `.claude/rules/navigation.md` §6, noting that it redirects.

Original finding follows.

**Where:** `.claude/rules/navigation.md:85-94` against `frontend/app/(app)/settings/page.tsx`

**What this is.** Rule §6 lists "the shape AskRepo is heading for" as a table of routes.

**Why this can happen.** The list runs `/`, `/projects`, `/projects/[id]`, `/ask`,
`/ask/[conversationId]`, `/checklist`, `/checklist/[moduleId]`, `/settings/users`. The
`/settings` index route exists on disk and is the redirect target rule §3 requires ("A group's
index route only redirects to its first reachable child"), but it is not in the table.

**What it costs.** Small: someone reading the rule to add a second settings child will not see
that the index route already exists and may add a second one.

**What we should do.** Add `/settings` to the table with a note that it redirects. Five minutes.

---

## §U10 Layout geometry, spacing, typography

### §U10.1 Geometry and type scale hold — 🟢 verified correct

**Where:** `components/layout/app-navbar.tsx:13`, `components/layout/app-sidebar.tsx:88`,
`components/layout/app-shell.tsx:22`

The navbar is `fixed … h-16`, the sidebar is `top-16 h-[calc(100vh-4rem)]`, and main content is
`mt-16 p-4 md:p-8` — all three derivations of the load-bearing `4rem` agree, and both files carry
a comment saying so. Every app screen wraps in `max-w-7xl` and both form shells in `max-w-3xl`,
matching [`docs/design.md`](design.md) → Layout. `font-bold` appears nowhere. No component sets a
font family. `font-mono` is applied consistently to file paths, repo URLs, commit SHAs, citations
and the module `source_path`.

### §U10.2 The item-filter grid contradicts the documented filter grid — 🟠 CONFIRMED — ✅ RESOLVED 2026-09-13

> Fixed: `item-filters.tsx` now uses the same `grid-cols-1 md:grid-cols-3
> lg:grid-cols-4 gap-4` geometry `ListToolbar` and `docs/design.md` specify.

Original finding follows.

**Where:** `components/checklist/item-filters.tsx:54` against
`components/layout/list-toolbar.tsx:30` and [`docs/design.md`](design.md):97

**What this is.** [`docs/design.md`](design.md) → Spacing specifies one geometry for the
filter/toolbar grid: `grid-cols-1 md:grid-cols-3 lg:grid-cols-4 gap-4`. `ListToolbar` implements
it exactly.

**Why this can happen.** `ItemFilters` renders `grid gap-3 sm:grid-cols-2 lg:grid-cols-4`,
differing on both the gap (`gap-3`, not `gap-4`) and the breakpoint ladder (`sm:2`, not `md:3`).
Its comment at lines 51-53 explains why it declares a row at all — it is rendered directly by the
screen rather than through `ListToolbar`'s `filters` slot — but not why the geometry differs.

**What it costs.** The module list's filters (through `ListToolbar`) and the module *detail*
grid's filters sit two clicks apart and reflow at different breakpoints with different gutters. On
a tablet at the `sm`–`md` range they visibly disagree. `gap-3` is on the approved interval list so
this is not an off-scale value — it is the wrong value for this context.

**What we should do.** Match the documented geometry, or route `ItemFilters` through
`ListToolbar`'s `filters` slot so there is one grid. Twenty minutes.

### §U10.3 Stat tiles exist in two sizes, and one four-up row disagrees with itself — 🟠 CONFIRMED — ✅ RESOLVED 2026-09-13

> Fixed within `project-stats.tsx`: its `Stat` helper gained `mono`/`title` props and
> now renders all four tiles at one size, closing the `text-xl`/`text-base` mismatch
> in that row. The dashboard's separate, larger (`text-3xl`) stat tiles were left as
> their own hand-rolled markup rather than forced onto the same component — the two
> contexts carry materially different visual weight (hero numbers vs. a compact 4-up
> row), and picking a winning size across them is a design call beyond this pass.

Original finding follows.

**Where:** `components/projects/project-stats.tsx:4-13` (the `Stat` helper), `:20-29` and `:30-40`
(two hand-rolled copies), against `app/(app)/dashboard-screen.tsx:50-69`

**What this is.** A stat tile is a `Card` holding a small muted label and a large value. The app
has five of them on two screens.

**Why this can happen.** Three problems stack:

1. `project-stats.tsx` defines a `Stat` helper and uses it for two of its four tiles (lines 18-19).
   The other two hand-roll the identical `Card`/`CardContent`/label/value markup because they need
   `font-mono` and a `title`, neither of which `Stat` accepts.
2. Those two copies then disagree with each other: the commit tile's value is `font-mono text-xl
   font-semibold` (line 25) while the embedding-model tile's is `font-mono text-base
   font-semibold` (line 34). **In a single four-column row, one value renders a size smaller than
   the other three.**
3. The dashboard's two tiles (lines 55, 65) use `text-3xl font-semibold` for the value, against
   `project-stats.tsx`'s `text-xl`. Same component shape, same `CardContent className="p-6"`, same
   label classes — different value size on a different screen.

**What it costs.** The four-up row on `/projects/[id]` is visibly ragged: three large values and
one smaller one, with no meaning attached to the difference. (The `text-base` was presumably
chosen because model names are long and `truncate` is applied — but truncation already handles
that, so the size drop is doing nothing the truncate is not.)

**What we should do.** Extend `Stat` with `mono?: boolean` and `title?: string`, use it for all
four tiles, and settle one value size for the app — then have the dashboard use the same helper.
About an hour.

### §U10.4 The same list-row link uses two different radii on two screens — 🟡 CONFIRMED — ✅ RESOLVED 2026-09-13

> Fixed: `dashboard-screen.tsx`'s two list-row links now use `rounded-lg`, matching
> `conversation-rail.tsx` and the corrected `docs/design.md` guidance (§U12.1).

Original finding follows.

**Where:** `app/(app)/dashboard-screen.tsx:108` and `:156` (`rounded-md`) against
`components/ask/conversation-rail.tsx:215` (`rounded-lg`)

**What this is.** Both render a hoverable list row linking to a conversation, with the same
`hover:bg-accent` treatment.

**Why this can happen.** The dashboard's "Your recent questions" rows use `rounded-md`; the
conversation rail's rows use `rounded-lg`. Both link to `/ask/[id]`, both truncate a title above a
muted timestamp.

**What it costs.** Minor, but it is the same object in two places with different corners, and the
dashboard row is the entry point to the rail row.

**What we should do.** Pick one — and note that [`docs/design.md`](design.md):68 says
`rounded-lg` for "sidebar links", which the rail effectively is. Ten minutes. See §U12.1: the
documented radius guidance is itself wrong, so settle that first.

---

## §U11 Icons and accessibility

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

### §U11.2 A long sentence is rendered inside a `Badge` — 🟡 CONFIRMED — ✅ RESOLVED 2026-09-13

> Fixed: `StalenessBadge` now reads "Stale" and carries the original advice in a
> `Tooltip` instead of stretching the pill.

Original finding follows.

**Where:** `components/checklist/staleness-badge.tsx:15`

**What this is.** `StalenessBadge` renders the text "Reindexed since — consider regenerating"
inside a `Badge`.

**Why this can happen.** Every other badge in the app holds one or two words — "Ready",
"Indexing", "Admin", "Member", "Review". `components/ui/badge.tsx:8` styles a badge as a fixed
`h-5` pill with `px-2` and `whitespace-nowrap`.

**What it costs.** Because it cannot wrap, the pill is several times the width of the status badge
it sits beside — at `module-table.tsx:100` inside a table cell, and at `module-screen.tsx:144`
directly after the page title and status badge. In the table it will force the "Last generated"
column wide on any row that is stale.

**What we should do.** Shorten the badge to "Stale" and move the advice into a `Tooltip` — the
component is already imported in `module-table.tsx:16`. Or render it as helper text rather than a
badge. Half an hour. The copy's carefulness is worth preserving: its docstring correctly notes it
must not imply that a passing *result* was invalidated.

---

## §U12 Documentation drift

### §U12.1 `docs/design.md` states the wrong radius for cards and dialogs — 📄 CONFIRMED — ✅ RESOLVED 2026-09-13

> Fixed: the Radius section in `docs/design.md` now states that `Card` and `Dialog`
> are `rounded-xl`, and that a hand-written panel meant to sit beside one should
> match.

Original finding follows.

**Where:** [`docs/design.md`](design.md):67-69 against `frontend/components/ui/card.tsx:15` and
`frontend/components/ui/dialog.tsx:56`

**What this is.** The Radius section reads: "Use `rounded-md` for cards and controls,
`rounded-lg` for the sidebar links and dialogs."

**Why this can happen.** The CLI-generated components disagree on both counts. `Card` is
`rounded-xl` (card.tsx:15, with `rounded-t-xl` / `rounded-b-xl` on its header and footer);
`DialogContent` is `rounded-xl` (dialog.tsx:56, with `rounded-b-xl` on the footer at :105). With
`--radius: 0.5rem` and `--radius-xl: calc(var(--radius) + 6px)` (globals.css:19, :176), that is
14px where the doc claims 8px for a card and 10px for a dialog.

**What it costs.** Someone hand-writing a surface meant to sit beside a `Card` will follow the doc,
reach for `rounded-md`, and produce a panel with visibly tighter corners than the cards around it.
Application code already spreads across `rounded-md` (26), `rounded-lg` (22), `rounded-xl` (5) and
`rounded-sm` (3) with no rule distinguishing them, which is the predictable outcome of a guidance
line nobody can follow.

**What we should do.** Correct the doc to describe what the components actually do, and state the
rule positively: cards and dialogs inherit `rounded-xl` from the generated components, hand-written
panels should match the surface they sit beside. Then reconcile the loose application-code usage
against it. Half an hour for the doc; §U10.4 is the first thing it settles.

### §U12.2 `docs/design.md`'s component inventory says nothing is installed — 📄 CONFIRMED — ✅ RESOLVED 2026-09-13

> Fixed: the Component inventory table in `docs/design.md` now lists the installed
> set — including `combobox`, `command`, `popover`, `sheet`, `pagination`, and
> `input-group`, which were missing — instead of claiming nothing is installed yet.

Original finding follows.

**Where:** [`docs/design.md`](design.md):104-106 against `frontend/components/ui/` (27 files)

**What this is.** The Component inventory section reads: "Nothing is installed yet — this table is
the intended set, and each row is added by `npx shadcn@latest add <name>` when the screen needing
it lands."

**Why this can happen.** Twenty-seven components are installed. The table is also now a subset of
what is there: `combobox`, `command`, `popover`, `sheet`, `sidebar`, `pagination`, `input-group`,
`field` and `avatar` are all in use and absent from the table — `sheet` most consequentially,
since `refinement-drawer.tsx` builds the app's drawer on it and the table lists no drawer surface
at all.

**What it costs.** The table's stated purpose is to be the checklist for what to install. It now
under-reports by nine components, so a developer consulting it to find out whether the app already
has a drawer primitive will conclude it does not and install or hand-roll a second one —
`refinement-drawer.tsx:84-89` records having faced exactly that decision about `resizable.tsx`.

**What we should do.** Replace the "nothing is installed yet" sentence with the real inventory and
add the missing rows, including a Drawer surface pointing at `sheet`. Under an hour.
`.claude/rules/documentation.md` makes this the kind of fact that must move with the code.

### §U12.3 Two documented tokens describe intentions rather than usage — 📄 — ✅ RESOLVED 2026-09-13

> Fixed as part of §U1.2: `info` now has a real caller and `chart-1…5` are marked
> reserved in `docs/design.md` rather than silently unused.

Original finding follows.

Covered at §U1.2. `info` and `chart-1…5` are listed in [`docs/design.md`](design.md):28 and :37
with stated purposes; nothing in the repository uses either.

---

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

**The sweep was read-only; a fix pass immediately after it was not.** Eighteen of this sweep's
findings are marked `— ✅ RESOLVED 2026-09-19` with a note on each. **Still open:** §U4.4 (item
result tones still mapped at the call site), §U5.7 (unmarked required fields on Add Member),
§U8.6 (a disconnect styled as a failure on the two refinement chats), §U8.7 (the mock-data change
set has no grouped overview), §U9.4 (the role matrix reaches Forbidden reactively), and §U10.8
(the `pl-9` SUSPECT).

**Ground truth unchanged:** [`design.md`](design.md), `.claude/rules/design-system.md`,
`.claude/rules/forms.md`, `.claude/rules/navigation.md`, `frontend/app/globals.css`, and
[`PRD.md`](PRD.md), which outranks them all.

**Numbering continues the sections above and never reuses a number.** A finding from 2026-09-13
that was found still resolved is not repeated here; where one has recurred in newly written code,
the new occurrence is its own finding and says which earlier one it echoes.

**No finding resolved on 2026-09-13 has regressed.** Every one was re-checked against the current
source. §U7.1's fix holds on all five screens it was applied to; §U8.1–§U8.4 hold in all three
streaming surfaces; §U5.1–§U5.6, §U6.1–§U6.3 and §U12.1–§U12.3 hold. What follows is new code, or
old code the earlier sweep did not reach.

## Top priorities

1. **Four surfaces tell a user "there is nothing here" when a request has actually failed**
   (§U7.4, §U7.5, §U7.6). This is one bug with three addresses, and it is the same bug §U7.1 fixed
   in March — on five screens that all still hold. These three simply landed afterwards.
2. **A menu item silently does nothing, whether it worked or not** (§U6.5), and it is not gated on
   the permission it needs, so the most likely outcome is a refusal nobody sees.
3. **An event's project id is unreadable** (§U10.6) on the one screen whose purpose is matching
   exact values against another system.
4. Everything else is consistency and documentation. Two of the findings (§U2.4, §U10.5) are
   defects in code written during this session, noted as such.

## §U2.4 The audit detail dialog hand-rolls a card instead of using `Card` — 🟡 — ✅ RESOLVED 2026-09-19

> Fixed. The dialog uses the real `Card`, at the same padding as the route.
>
> Original finding follows.


**Where:** `frontend/components/audit/audit-detail-dialog.tsx:79` versus
`frontend/app/(app)/settings/audit/[eventId]/audit-event-screen.tsx:87`

**What this is.** The audit detail body was deliberately extracted into
`components/audit/audit-event-detail.tsx` so the route and the dialog render one implementation
rather than two — its docstring says exactly that. `AuditEventCurrent` is the "As of now" block:
live lookups fenced off from the recorded snapshot so a present-tense answer cannot be mistaken for
part of the record.

**Why this can happen.** The route wraps that block in the real `Card` component at `p-6`. The
dialog wraps it in a bare `<div className="border-info/40 bg-info/5 rounded-xl border p-4">` — a
`Card`-shaped div, with `Card`'s radius and border copied out as literal classes. The extraction's
docstring justifies the *other* wrapper split (Cards on the route, stacked in the dialog, for
`AuditEventFacts`) but says nothing about this one, so it is not a recorded decision.

**What it costs.** Nothing visible today; the two render nearly identically. The cost arrives when
`Card`'s tokens move — its radius, its ring, its surface — at which point the route updates and the
dialog silently does not. That is §U2.1 and §U2.3's failure mode exactly, recurring in code written
after those were fixed.

**What we should do.** Use `Card` in the dialog too, and settle on one padding. Ten minutes.
CONFIRMED.

## §U3.4 The audit table's columns are ordered against the documented list skeleton — 🟠 — ✅ RESOLVED 2026-09-19

> Fixed, per the owner's decision to follow the list skeleton: the audit table now
> reads Event → Outcome → Actor → Target → Changed → Time → Actions. The comment
> records that chronology is expressed by the default sort, not by column order.
>
> Original finding follows.


**Where:** `frontend/components/audit/audit-table.tsx:22` (the comment stating the order) and
`:38-46` (the header row), against [`design.md`](design.md) → Lists

**What this is.** Every list screen in the app follows one column order: identity first, status
second, timestamps last, actions in a right-aligned final column. `components/users/user-table.tsx`
and `components/roles/role-table.tsx` both follow it.

**Why this can happen.** The audit table renders Time → Event → Actor → Target → Outcome → Changed
→ Actions. The timestamp is first rather than last and the status ("Outcome") is fourth rather than
second. Since the two sibling admin tables follow the documented order, this is local drift rather
than a project-wide reinterpretation.

**What it costs.** No data is hidden or wrong. An operator moving between `/settings/audit` and
`/settings/users` reads two tables of the same shape in a different order. The larger cost is that
the next column added here has no convention to anchor to, because this table already departed from
it.

**What we should do.** There is a real argument the other way — an audit trail is a chronological
record and "when" is arguably its identity — so this is a question for the owner rather than an
obvious edit. If the answer is "follow the skeleton", reorder to Event → Outcome → Actor → Target →
Changed → Time → Actions. If the answer is "time leads, deliberately", record that as a stated
exception in [`design.md`](design.md) → Lists so the next table does not copy it blindly.
CONFIRMED.

## §U4.4 A third status domain picks its colours at the call site — 🟡

**Where:** `frontend/components/checklist/item-grid.tsx:82-87`, against `frontend/lib/status.ts`

**What this is.** `.claude/rules/design-system.md` §5 requires each status domain to map to a tone
in exactly one module, so a badge, a table row and a detail header showing the same state cannot
disagree. `lib/status.ts` owns the project mapping and `components/checklist/module-status-badge.tsx`
owns the module mapping — the two §U4.1 consolidated.

**Why this can happen.** A checklist item's result — `untested` / `pass` / `fail` / `blocked` — is a
third domain, and its tone table is declared locally inside the grid component rather than beside
the other two.

**What it costs.** Nothing today: the vocabulary does not collide with the project or module words,
so the rule's guarantee holds by coincidence rather than by construction. The cost is the next
component needing this state's colour — a dashboard tile, a filter chip — which has nothing to
import and will re-derive its own mapping, reopening the "badge colour decided four ways" problem
§U4.1 closed once already.

**What we should do.** Move the tone and label tables into `lib/status.ts` beside the module
mapping and import them. An hour. CONFIRMED.

## §U4.5 `text-destructive` is back in hand-written code — 🟡 — ✅ RESOLVED 2026-09-19

> Fixed. Both sites use `text-danger`.
>
> Original finding follows.


**Where:** `frontend/components/projects/member-table.tsx:94` and
`frontend/components/checklist/change-set-panel.tsx:272`

**What this is.** `globals.css` defines `destructive` as an alias of `danger` so CLI-generated
components can keep saying `destructive` while hand-written code says `danger` — the split §U4.3
established and fixed.

**Why this can happen.** Both sites are hand-written and use the generated-code spelling.

**What it costs.** Nothing visual; they resolve to the same colour. It costs the grep: someone
auditing where this app shows danger colour searches `text-danger` and misses these two. That is
the entire reason §U4.3 was filed.

**What we should do.** Change both to `text-danger`. Five minutes. CONFIRMED.

## §U5.7 The Add Member dialog does not mark its required fields — 🟠

**Where:** `frontend/components/projects/add-member-dialog.tsx:100-101` and `:132-133`

**What this is.** Required fields carry a trailing asterisk in `text-danger`. Every comparable
dialog does it — `create-project-dialog.tsx`, `create-user-dialog.tsx`, and
`create-module-dialog.tsx`, which includes the precedent for a required `Select`.

**Why this can happen.** Neither the User nor the Role label carries the marker, though User is
strictly required — `handleSubmit` returns early without it — and Role always carries a value.

**What it costs.** The same cost §U5.2 named on the login screen: the app teaches a convention on
one form and breaks it on the next, so the marker stops being information.

**What we should do.** Add the asterisk span to both labels, following
`create-module-dialog.tsx`'s required-`Select` precedent. Ten minutes. CONFIRMED.

## §U5.8 The module edit dialog reopens with an abandoned draft — 🟠 — ✅ RESOLVED 2026-09-19

> Fixed. Opening the dialog re-seeds both fields from the module, as
> `item-grid`'s `startEditing` does.
>
> Original finding follows.


**Where:** `frontend/components/checklist/module-row-actions.tsx:33-34`, against
`frontend/components/checklist/item-grid.tsx:139-147`

**What this is.** `forms.md` §6 requires an edit form to seed from the fetched record during
render, keyed so that reopening on a different row re-seeds.

**Why this can happen.** `editingName` and `editingPath` are seeded once by `useState` at first
mount of the row and never re-synced. Opening the dialog only sets a boolean. The row component
stays mounted as long as the list does, so the state survives a cancel. `item-grid.tsx`'s
`startEditing()` does this correctly for the comparable case, re-seeding the draft from the row's
current values every time Edit is clicked.

**What it costs.** Open Edit, type a new name, press Cancel, reopen Edit on the same module: the
dialog shows the abandoned text, not the module's saved name. A user can mistake their own
discarded draft for the record's real value and submit it as a deliberate edit.

**What we should do.** Re-seed both fields from the module when the dialog opens, mirroring
`startEditing()`. Half an hour. CONFIRMED.

## §U6.5 Generating from the module list's row menu reports nothing, and is not gated — 🔴 — ✅ RESOLVED 2026-09-19

> Fixed. The row menu wires the same success and error toasts the module screen
> uses, and the item is now disabled with a reason when the caller lacks
> `generate.run` — the permission it always needed.
>
> Original finding follows.


**Where:** `frontend/components/checklist/module-row-actions.tsx:112`, against
`frontend/app/(app)/checklist/[moduleId]/module-screen.tsx:193-208`

**What this is.** Generating a checklist is expensive work — it scrolls the whole index and runs a
chat model — and it can legitimately refuse: a generation is already running, a pending change set
is waiting, the index is mid-reindex, or the caller lacks the permission.

**Why this can happen.** The row menu calls `generate.mutate()` with no `onSuccess` and no
`onError`, and the hook itself only invalidates a query on success. The same mutation, from the
module's own screen two files over, wires both a success and an error toast. The row-menu path was
the one place it was skipped. Separately, the menu item is gated on the edit and delete permissions
but not on the generate permission the page's own button checks — so a user without it sees an
enabled control.

**What it costs.** A click that failed looks exactly like a click that worked: the menu closes and
nothing else happens. For the most likely failure — a user who lacks the permission — the backend
correctly refuses and the refusal vanishes. The user waits for a result that is never coming.

**What we should do.** Wire the same success and error toasts the module screen uses, and gate the
item on the generate permission so it matches the page. Half an hour. CONFIRMED.

## §U6.6 Deleting a test case confirms nothing — 🟠 — ✅ RESOLVED 2026-09-19

> Fixed. Deleting a test case toasts on success.
>
> Original finding follows.


**Where:** `frontend/components/checklist/item-grid.tsx:453-464`

**What this is.** [`design.md`](design.md) → Feedback: a successful mutation ends in a brief toast.
Every sibling delete does it — module, project, conversation, role, mock-data record.

**Why this can happen.** The delete's `onSuccess` only closes the dialog. The error path is handled.

**What it costs.** A tester deletes a test case and gets no confirmation. The row vanishing from a
long, filtered grid is easy to miss, so the natural check is to look for the row — which is a worse
experience than being told.

**What we should do.** Add a success toast matching the siblings' voice. Ten minutes. CONFIRMED.

## §U6.7 Toast voice is split down the middle — 🟡 needs a decision — ✅ RESOLVED 2026-09-19

> Settled by the owner: **bare phrase is the house style.** All eleven
> name-interpolated toasts were rewritten, so all thirty now read one way.
>
> Original finding follows.


**Where:** 19 bare-phrase toasts and 11 name-interpolated ones. Bare: `module-screen.tsx:196`,
`change-password-screen.tsx:27`, `conversation-rail.tsx:72`, `records-table.tsx:62`,
`mock-data/change-set-panel.tsx:90,105`, `add-member-dialog.tsx:78`,
`mock-data/generate-control.tsx:36`, `edit-user-dialog.tsx:40`, `item-grid.tsx:161,347`,
`create-item-dialog.tsx:72`, `users/change-password-dialog.tsx:29`,
`checklist/change-set-panel.tsx:121,136`, `create-module-dialog.tsx:79`,
`module-row-actions.tsx:71`, `project-row-actions.tsx:120-122`, `module-screen.tsx:305-308`.
Name-interpolated: `role-matrix-screen.tsx:90`, `member-table.tsx:70,134`,
`project-row-actions.tsx:140`, `role-row-actions.tsx:77`, `create-project-dialog.tsx:48`,
`create-user-dialog.tsx:30`, `create-role-dialog.tsx:37`, `user-row-actions.tsx:72`,
`reset-password-dialog.tsx:30`, `module-row-actions.tsx:186`.

**What this is.** Toasts are the most-seen copy in the app, and one voice for one kind of event is
what stops a product reading as though several people assembled it.

**Why this can happen.** §U6.4's fix on 2026-09-13 addressed the *explanatory two-sentence* toasts
and rewrote them terse. The bare-versus-named split was never the part it settled, and it has grown
since: at least six of the eleven named toasts are on roles, members and projects work that landed
or was touched afterwards.

**What it costs.** Low and cumulative. "Module updated" and "`${module.name}` deleted" fire from the
same menu, one naming the thing and one not.

**What we should do.** This is a decision, not a defect — neither voice is wrong, and the report
deliberately does not pick one. Bare is the majority at 19 to 11. Once chosen, the minority is a
mechanical rewrite of under an hour, and the choice belongs in [`design.md`](design.md) → Feedback
so the next screen does not re-split it. CONFIRMED.

## §U7.4 The Members table renders a failed request as an empty table — 🔴 — ✅ RESOLVED 2026-09-19

> Fixed. The table branches on `isError` with `ListError` and a retry, and has an
> empty state of its own.
>
> Original finding follows.


**Where:** `frontend/components/projects/member-table.tsx:151-182`

**What this is.** The Members tab on a project answers "who can reach this repository, and with
what role". It is the screen an owner opens to check access.

**Why this can happen.** The body branches on `query.isLoading` and otherwise maps
`query.data ?? []`. There is no error branch anywhere in the file, and no empty state.

**What it costs.** When `GET /projects/{id}/members` fails — a network blip, a `500`, a
session-refresh race after the project query already succeeded — the tab renders its header row and
no rows at all. That is visually indistinguishable from "this project has no members", which cannot
legitimately happen: every project keeps at least one owner. An owner auditing access is told,
silently and confidently, that access has been revoked from everyone.

**What we should do.** Add the `isError` branch with `ListError` and a retry, ahead of the empty
check, exactly as `/projects`, `/settings/users`, `/checklist` and the dashboard already do.
Half an hour. CONFIRMED.

## §U7.5 The conversation rail renders a failed request as "Nothing yet" — 🔴 — ✅ RESOLVED 2026-09-19

> Fixed. The rail branches on `isError` ahead of the empty state, and the project
> filter distinguishes a failed load from no match.
>
> Original finding follows.


**Where:** `frontend/components/ask/conversation-rail.tsx:136-144` and `:216-234`; the project
filter beside it at `:125-130` and `:195-197`

**What this is.** The rail lists the caller's own conversations, on every `/ask` page load, in the
sidebar and the mobile sheet.

**Why this can happen.** `conversations = query.data?.items ?? []`. On a failure `data` is
undefined and `isLoading` is false, so the empty branch renders. `query.isError` is never read
anywhere in the file. The project filter has the same gap: its empty message says "No project
matches" whether the list is genuinely empty or the request failed.

**What it costs.** A user with a full history, who asked something two minutes ago, is told
"Nothing yet. Pick a project and ask a question." That does not read as a transient failure — it
reads as data loss. There is no retry affordance, and the detail view one component over
(`conversation-screen.tsx:64-71`) handles the same class of failure correctly with `DetailError` and
an explicit retry.

**What we should do.** Branch `isError` ahead of the empty check and render the compact error the
refinement chats' own message lists already use. Half an hour. CONFIRMED.

## §U7.6 The Mock Data tab has a loading state and an error state for the wrong query — 🔴 — ✅ RESOLVED 2026-09-19

> Fixed. `RecordsTable` is gated on the dataset query's own loading and error
> states, which the screen-level gate never covered.
>
> Original finding follows.


**Where:** `frontend/app/(app)/checklist/[moduleId]/module-screen.tsx:94,107,361,377,400-409` and
`frontend/components/mock-data/records-table.tsx:87-101`

**What this is.** The module screen gates correctly on its own query — `isLoading` and `error` are
both handled before the tabs render at all. But the Mock Data tab fetches its dataset separately,
from inside the already-rendered tab.

**Why this can happen.** Every reference to that second query reads `mockData.data?.…`. Neither
`mockData.isLoading` nor `mockData.isError` is read anywhere. `RecordsTable` takes only the records
array and renders `EmptyState` whenever it is empty — which is also true before the fetch resolves,
and also true when it fails.

**What it costs.** Switching to the Mock Data tab on a module that *has* records shows "No mock data
yet — Generate a batch, or ask for one by chat" until the fetch lands. If the fetch fails, that
invitation to generate a batch stays up permanently, over a dataset that already exists. Acting on
it is a wasted model run against work that was already done.

**What we should do.** Gate `RecordsTable` on `mockData.isLoading` with a skeleton and
`mockData.isError` with `ListError`, the shape `checklist-screen.tsx` already uses. Half an hour.
CONFIRMED.

**These three are one finding with three addresses.** §U7.1 established the pattern and fixed it on
five screens, all of which still hold. These three surfaces landed afterwards and never received
it. The useful conclusion is not "three bugs" but that the fix was never turned into something that
propagates — see the note under §U7.1's resolution. A lint rule, a shared list-body component, or a
test asserting every `useQuery` consumer reads `isError` would each have caught all three.

## §U8.6 A dropped connection is a red failure on two surfaces and a grey note on the third — 🟠

**Where:** `frontend/app/(app)/ask/[conversationId]/conversation-screen.tsx:151-155` versus
`frontend/components/checklist/chat-panel.tsx:186-195,292-297` and
`frontend/components/mock-data/chat-panel.tsx:155-161,256-261`

**What this is.** All three surfaces are served by the same `Answerer`, and a client disconnect is a
specific, benign server-side event: the shielded write in `finally` persists the partial answer with
`finishReason: "disconnected"`. Nothing failed.

**Why this can happen.** The Ask screen models three terminal states — done, error, and
`interrupted` — and renders the third as a quiet line: "The connection dropped. What arrived above
is kept." The two refinement chats model only two: their turn state has a single `errorMessage`, so
the disconnect string is funnelled into the same destructive `Alert`, titled "The reply stopped",
that a genuine mid-stream failure uses.

**What it costs.** The same event is communicated at two different severities to two different
audiences — and the alarming one is on the *shared* surfaces, where a checklist or dataset is
published to everyone on the instance. A reviewer sees a red failure banner for something the
product deliberately treats as fine, with the kept content sitting directly above it.

**What we should do.** Give both refinement panels the same three-way terminal split the Ask screen
has, and reserve the destructive `Alert` for real errors. Two hours. CONFIRMED.

## §U8.7 The mock-data change set lost the grouping its twin has — 🟡

**Where:** `frontend/components/mock-data/change-set-panel.tsx:145-171` versus
`frontend/components/checklist/change-set-panel.tsx:158-171` and `:183-303`

**What this is.** A change set is a list of `add` / `update` / `remove` operations a human ticks
before applying. Both panels carry the same taxonomy — both files switch on the same `op` field.

**Why this can happen.** The checklist panel shows a summary line ("3 added, 1 changed, 2 removed")
and separates the operations into headed sections. The mock-data panel renders one flat divided
list with no counts and no headings. §U8.3 unified these panels at the *row* level by extracting
`OperationRow`; the list structure above the rows was not carried across.

**What it costs.** The mock-data reviewer of a mixed change set gets no at-a-glance shape and no
visual separation between kinds, on exactly the change sets where scanning matters. The checklist
reviewer of the identical interaction gets both.

**What we should do.** Decide once, and record it. Either factor the summary and grouping into a
shared list wrapper both panels use, or state in a comment that mock data is deliberately flat —
the way `mock-data/chat-panel.tsx` already documents its own deliberate divergences. Right now it
is neither, which is what makes it drift rather than a choice. Two hours. CONFIRMED.

## §U8.8 The two change-set panels disagree about card rhythm, and the checklist one is off-spec — 🟡 — ✅ RESOLVED 2026-09-19

> Fixed. The checklist panel uses `space-y-4`, matching the documented rhythm and
> its twin.
>
> Original finding follows.


**Where:** `frontend/components/checklist/change-set-panel.tsx:173` (`space-y-6`) versus
`frontend/components/mock-data/change-set-panel.tsx:135` (`space-y-4`), against
[`design.md`](design.md) → Spacing, which names `space-y-4` as the vertical rhythm inside a card

**What it costs.** Purely visual, and both values are on the documented interval scale. But the
checklist panel's sections sit visibly further apart than its near-twin's, which is the opposite of
what two panels built from one component should produce — and it is the non-conformant one.

**What we should do.** Change the checklist panel to `space-y-4`, or, if the three-section layout
genuinely needs the air, say so in a comment and record the exception in [`design.md`](design.md).
Five minutes. CONFIRMED.

## §U9.3 The navigation rule's route list is two whole sub-trees out of date — 📄 — ✅ RESOLVED 2026-09-19

> Fixed. All four roles and audit routes are in `.claude/rules/navigation.md` §6.
>
> Original finding follows.


**Where:** `.claude/rules/navigation.md` §6, against `frontend/app/(app)/settings/roles/page.tsx`,
`settings/roles/[id]/page.tsx`, `settings/audit/page.tsx` and `settings/audit/[eventId]/page.tsx`

**What this is.** §6 is the rule's canonical picture of the route shape the app is heading for.

**Why this can happen.** It lists `/settings` and `/settings/users` and stops. Four admin routes
have shipped since. §U9.2 already fixed one missing row in this same table on 2026-09-13, so this is
the same gap recurring rather than a one-off. `CLAUDE.md`'s frontend list, by contrast, is complete
and correct — it is only the rule that is stale.

**What it costs.** Someone planning a new settings child reads the rule as ground truth and sees a
picture missing the two most recent siblings, including the one whose column order they might have
copied.

**What we should do.** Add all four rows, mirroring `CLAUDE.md`. Ten minutes. CONFIRMED.

## §U9.4 One admin screen reaches Forbidden reactively rather than immediately — 🟠

**Where:** `frontend/app/(app)/settings/roles/[id]/role-matrix-screen.tsx:25-72`, against
`roles-screen.tsx:35-36`, `users-screen.tsx:37-38`, `audit-screen.tsx:48-49` and
`audit-event-screen.tsx:30-31`

**What this is.** Every admin screen opens with a synchronous `if (!user.isAdmin) return
<Forbidden />`, commented as mirroring the backend gate rather than replacing it — because hiding a
sidebar item is not gating a route, and an operator can type a URL.

**Why this can happen.** The role matrix screen has no such check. It fires both its queries
unconditionally and only renders `Forbidden` if and when a query returns `403`.

**What it costs.** Not a bypass: the backend enforces `require_admin` and the `403` branch exists,
so the route does end up correctly forbidden. What a non-admin sees is a loading skeleton first —
contentless, so nothing leaks — where every sibling screen shows Forbidden at once. The real cost is
that this is the screen someone will copy as the template for the next admin detail page, and the
invariant asserted everywhere else is not actually true here.

**What we should do.** Add the same synchronous gate ahead of the loading branch. Ten minutes.
CONFIRMED.

## §U10.5 The documented filter-grid geometry is now only half true — 📄 — ✅ RESOLVED 2026-09-19

> Fixed. `docs/design.md` → Spacing documents the five-cell variant and states that
> filters are passed as sibling cells, never a nested grid — which is the mistake that
> caused the clipped filter row in the first place.
>
> Original finding follows.


**Where:** [`design.md`](design.md) → Spacing, against
`frontend/components/layout/list-toolbar.tsx:13-16` and
`frontend/app/(app)/settings/audit/audit-screen.tsx:64`

**What this is.** [`design.md`](design.md) states one filter/toolbar geometry:
`grid-cols-1 md:grid-cols-3 lg:grid-cols-4`.

**Why this can happen.** `ListToolbar` grew a second five-cell layout for the audit screen, which
carries a search box plus four filters. The change landed in commit `6d084bf` **during this
session** and the document was not updated in the same change, which `.claude/rules/design-system.md`
§6 requires.

**What it costs.** Small today, since the two layouts agree at the `md` breakpoint. The cost is that
the next person auditing whether a filter row is on-spec reads one fixed geometry and cannot
distinguish the deliberate five-column screen from drift.

**What we should do.** Add the five-column variant to [`design.md`](design.md) → Spacing, as "four
cells by default, five when a screen carries four or more filters". Ten minutes. CONFIRMED.

## §U10.6 A project id renders in the body face on the screen built for matching exact values — 🟡 — ✅ RESOLVED 2026-09-19

> Fixed. The project id renders `font-mono`.
>
> Original finding follows.


**Where:** `frontend/components/audit/audit-event-detail.tsx:63-65`, rendered by both
`/settings/audit/[eventId]` and the detail dialog

**What this is.** [`design.md`](design.md) → Typography puts `font-mono` on every file path, commit
hash and identifier, and §U10.1 verified that holds for citations, repo URLs and module source
paths.

**Why this can happen.** The Project field renders a raw UUID through the generic `Field` helper,
which sets no font. It is a new identifier field that the convention never reached.

**What it costs.** An operator reading an audit row is usually there to match it against something
else — a ticket, a log line, another screen. In the proportional body face a UUID does not
distinguish `0` from `O` or `1` from `l`, which is the entire reason identifiers are mono
everywhere else in the app.

**What we should do.** Render the value `font-mono`, either at the call site or by giving `Field` a
`mono` option the way `Stat` was extended in §U10.3. Fifteen minutes. CONFIRMED.

## §U10.7 Two tab section headings are one size apart — 🟡 — ✅ RESOLVED 2026-09-19

> Fixed. The Members heading is `text-xl`, matching the Mock Data tab.
>
> Original finding follows.


**Where:** `frontend/app/(app)/projects/[id]/project-detail-screen.tsx:125` (`text-lg`) versus
`frontend/app/(app)/checklist/[moduleId]/module-screen.tsx:332` (`text-xl`)

**What this is.** Both are the same structure: a section heading inside a tab, with a description
beside it and a primary action to its right. [`design.md`](design.md)'s type scale names `text-xl`
for a card or section title; `text-lg` appears nowhere else in application code.

**What it costs.** The Members tab's heading reads visibly smaller than the Mock Data tab's for no
reason a user can discover.

**What we should do.** Move the Members heading to `text-xl`, matching the scale and the precedent.
Five minutes. CONFIRMED.

## §U10.8 Two search inputs carry an off-scale padding — 🟡 SUSPECT

**Where:** `frontend/components/layout/list-toolbar.tsx:51` and
`frontend/components/ask/conversation-rail.tsx:168`, both `pl-9`

**What this is.** Spacing comes from the documented intervals `1, 2, 3, 4, 6, 8, 12`. Nine is not
among them.

**Why this is SUSPECT rather than confirmed.** `pl-9` is the standard recipe for clearing a
`left-3 size-4` icon, and the rule allows deviation "with a reason worth a comment". The reason is
almost certainly that — but no comment says so, so a reader cannot tell a considered exception from
an accident. What would settle it: whether any other value clears the icon cleanly.

**What we should do.** Either add the one-line comment pointing at the icon it clears, or record
icon-padded inputs as a carve-out in [`design.md`](design.md). Five minutes.

## §U11.3 A third icon size has appeared in four places — 🟡 — ✅ RESOLVED 2026-09-19

> Fixed. All four icons are `size-4`.
>
> Original finding follows.


**Where:** `frontend/components/roles/role-badge.tsx:14` and
`frontend/components/audit/audit-change-list.tsx:98` (both new), plus the pre-existing
`frontend/components/form/password-field.tsx:92,94` and
`frontend/components/checklist/path-picker.tsx:122`

**What this is.** [`design.md`](design.md) → Icons gives exactly two sizes: `size-4` inline with
text, `size-5` standalone.

**Why this can happen.** `size-3.5` and `size-3` are neither. `role-badge.tsx`'s own docstring says
it is modelled on `user-role-badge.tsx` — but that component carries no icon at all, so the figure
was picked independently rather than copied from a precedent.

**What it costs.** The lock beside a system role and the before/after arrow in the audit change list
are slightly smaller than the app's two sanctioned sizes. Minor, but it is now a third size in four
places, two of them added since the last sweep.

**What we should do.** Move all four to `size-4`, or comment the cramped-row reason if one exists.
Twenty minutes. CONFIRMED.

## §U12.4 The component inventory documents an app without roles or audit — 📄 — ✅ RESOLVED 2026-09-19

> Fixed. `docs/design.md`'s component inventory gains a Roles row and an Audit row.
>
> Original finding follows.


**Where:** [`design.md`](design.md) → Component inventory, against `frontend/components/roles/` and
`frontend/components/audit/`

**What this is.** The inventory table lists which shadcn components each surface uses, so nobody
runs `shadcn add` for something already installed.

**Why this can happen.** It has rows for auth, the app shell, projects, Dev Knowledge, QA Checklist,
the Mock Data tab, the refinement chats and lists — and none for the two surfaces that shipped
since. Between them those directories use `alert`, `badge`, `button`, `card`, `checkbox`, `combobox`,
`dialog`, `dropdown-menu`, `field`, `input`, `separator`, `skeleton` and `table`.

**What it costs.** Someone consulting the inventory would not learn that `checkbox`, `combobox` and
`separator` are already in use outside QA Checklist, or that a dialog and two tables exist on
undocumented surfaces.

**What we should do.** Add a Roles row and an Audit row. Fifteen minutes. CONFIRMED.

## §U1.3 The "only `globals.css` may hold a raw colour" rule has an unrecorded exception — 📄 — ✅ RESOLVED 2026-09-19

> Fixed. `.claude/rules/design-system.md` §2 now names `manifest.ts` as the one
> exception and says why the browser needs literal values there.
>
> Original finding follows.


**Where:** `.claude/rules/design-system.md` §2 and [`design.md`](design.md), against
`frontend/app/manifest.ts:23-24`

**What this is.** The rule states that `frontend/app/globals.css` is the only file permitted to
contain a raw hex colour.

**Why this can happen.** `manifest.ts` carries two — `theme_color` and `background_color` — and it
legitimately must: the browser reads them to paint its own chrome before any stylesheet loads, so
they cannot be tokens. The file's docstring says exactly this, and keeps the two values as literal
mirrors of `--primary` and `--background`.

**What it costs.** The code is right and the rule's sentence is now literally false of the
repository. A future sweep either files a non-finding or, worse, "fixes" the manifest into something
the browser cannot read.

**What we should do.** Add a one-line carve-out to the rule naming `manifest.ts` and why. Ten
minutes. CONFIRMED.

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

## See also

- [`audit-findings.md`](audit-findings.md) — the backend/architecture sweep (`§1`–`§9`)
- [`design.md`](design.md) — the design reference these findings are measured against
- [`../.claude/rules/design-system.md`](../.claude/rules/design-system.md),
  [`../.claude/rules/forms.md`](../.claude/rules/forms.md),
  [`../.claude/rules/navigation.md`](../.claude/rules/navigation.md) — the enforceable rules
- [`../.claude/commands/audit-ui.md`](../.claude/commands/audit-ui.md) — how this sweep is run
- [`../.claude/rules/audit-findings.md`](../.claude/rules/audit-findings.md) — how a finding is written
