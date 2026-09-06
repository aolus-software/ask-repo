# AskRepo design system

The reference `.claude/rules/design-system.md` points at. Palette values come from the
[Fexend](https://github.com/fexend/fexend-html) design system; the token structure is
semantic-role-per-token so dark mode is a change to one file.

`frontend/app/globals.css` is the implementation and the **only** file in the repo permitted to
contain a raw hex colour. This document and that file change together.

## Tokens

Every token is defined twice — once in `:root`, once in `.dark` — and exposed to Tailwind
through `@theme inline` as `--color-<name>`. Components use the utility (`bg-card`), never the
variable and never a hex value.

| Role | Light | Dark | Utility |
| --- | --- | --- | --- |
| `background` | `#f1f5f9` | `#020617` | `bg-background` — the page behind everything |
| `foreground` | `#0f172a` | `#f1f5f9` | `text-foreground` — default body text |
| `card` | `#ffffff` | `#0f172a` | `bg-card` — every raised surface |
| `card-foreground` | `#0f172a` | `#f1f5f9` | `text-card-foreground` |
| `popover` | `#ffffff` | `#0f172a` | dropdowns, dialogs, command palette |
| `primary` | `#615fff` | `#7c86ff` | `bg-primary` — brand, primary action, active nav |
| `secondary` | `#9333ea` | `#c27aff` | secondary emphasis |
| `success` | `#00c950` | `#05df72` | project `ready`, verified QA pair |
| `warning` | `#f59e08` | `#ffb900` | project `indexing`, unverified |
| `danger` | `#fb2c36` | `#ff6467` | project `failed`, destructive action |
| `info` | `#00b8db` | `#00d3f2` | neutral notice |
| `destructive` | → `danger` | → `danger` | alias so shadcn-generated components match |
| `muted` | `#f1f5f9` | `#1d293d` | `bg-muted` — inset panels, table headers |
| `muted-foreground` | `#62748e` | `#90a1b9` | secondary text, placeholders |
| `accent` | `#f1f5f9` | `#1d293d` | hover surface |
| `border` | `#e2e8f0` | `#1d293d` | every divider and card edge |
| `input` | `#cad5e2` | `#45556c` | form control borders (darker than `border`) |
| `ring` | `#615fff` | `#7c86ff` | focus ring |
| `sidebar*` | `#ffffff` | `#0f172a` | eight sidebar-specific roles |
| `chart-1…5` | see file | see file | retrieval scores, eval results |

Each colour role has a paired `-foreground` giving the text colour that sits on it. `bg-primary`
always takes `text-primary-foreground`, never `text-white` — white is wrong the moment a token
changes.

**Status colours are semantic.** A project's `status` maps to `success` / `warning` / `danger`,
never to a hand-picked green. That mapping lives in one place so a badge, a row, and a detail
header cannot disagree.

## Typography

**Lexend** for everything (`font-sans`, wired in `app/layout.tsx` via `next/font/google`).
**Geist Mono** for code, commit SHAs, file paths, and identifiers (`font-mono`).

| Use | Classes |
| --- | --- |
| Page title | `text-3xl font-semibold tracking-tight` |
| Card / section title | `text-xl font-semibold` |
| Body | `text-base leading-7` |
| Secondary body | `text-base text-muted-foreground` |
| Label, table header | `text-sm font-medium` |
| Helper, timestamp | `text-xs text-muted-foreground` |
| Code, SHA, path | `font-mono text-sm` |

Never set a font family in a component. Never use `font-bold` — `font-semibold` is the heaviest
weight in the system.

## Radius

`--radius: 0.5rem` with `sm`/`md`/`lg`/`xl` derived from it. Use `rounded-md` for cards and
controls, `rounded-lg` for the sidebar links and dialogs, `rounded-full` only for avatars and
pills. Never a literal `rounded-[10px]`.

## Layout

The shell geometry, taken from Fexend:

| Element | Size |
| --- | --- |
| Navbar | fixed top, `h-16` (4rem), `z-50`, `bg-card` with `border-b` |
| Sidebar | `w-64` (16rem), `top-16`, `h-[calc(100vh-4rem)]`, `z-40`, `bg-sidebar` with `border-e` |
| Icon rail (optional) | `w-16` |
| Main content | `mt-16 p-4 md:p-8` |
| Content max width | `max-w-7xl` for lists, `max-w-3xl` for forms and prose |
| Mobile sidebar | off-canvas with `sidebar-backdrop` (`bg-black/30 backdrop-blur-sm`, `z-30`) |

The `4rem` navbar height appears in the sidebar's `top` and `height` calculations. It is a token
in spirit — change it in one place and check both.

## Spacing

Tailwind's default scale, used at these intervals only: `1, 2, 3, 4, 6, 8, 12`. Vertical rhythm
inside a card is `space-y-4`; between cards, `gap-6`.

| Context | Spacing |
| --- | --- |
| Card padding | `p-6` (`p-4` compact, `p-8` roomy) |
| Card header margin | `mb-4` |
| Form field gap | `gap-1` within a field, `mb-4` between fields |
| Filter/toolbar grid | `grid-cols-1 md:grid-cols-3 lg:grid-cols-4 gap-4` |
| Button group | `gap-2` |
| Page section gap | `gap-6` |

## Component inventory

Components come from **shadcn on the Base UI base**, installed via CLI into
`frontend/components/ui/`, restyled by the tokens above. Nothing is installed yet — this table
is the intended set, and each row is added by `npx shadcn@latest add <name>` when the screen
needing it lands.

| Surface | Components |
| --- | --- |
| Auth screens | `button`, `input`, `label`, `field`, `card`, `alert`, `dialog`, `sonner` |
| App shell | `sidebar`, `breadcrumb`, `dropdown-menu`, `avatar`, `separator`, `skeleton` |
| Projects | `table`, `badge`, `select`, `tooltip`, `progress` |
| Dev Knowledge | `textarea`, `scroll-area`, `collapsible` |
| QA Checklist | `table`, `textarea`, `tooltip`, `select`, `checkbox`, `alert`, `dropdown-menu` |
| Mock Data tab | `tabs` |

`form` is deliberately absent: shadcn's `form` component wraps **react-hook-form**, which
`.claude/rules/forms.md` §4 bans by name — validation is owned by the backend's `422` field map,
and a client-side copy of a rule like the password policy cannot be kept honest. `field` is the
composition primitive instead. `dialog` sits in the auth row because every auth form is a dialog by
`forms.md` §1's count (create user, reset password, change own password).

Hand-writing a component shadcn provides is a rule violation, not a shortcut — see
`.claude/rules/design-system.md`.

## Lists

Every list screen has the same skeleton:

1. Page header — title, description, primary action button on the right.
2. Toolbar — search input plus filters in the filter grid above.
3. `card-table` surface — a `Card` with no padding wrapping a `Table`.
4. Pagination footer inside the same card.

- Column order: identity first, status second, timestamps last, actions in a right-aligned final
  column.
- Timestamps are relative with an absolute `title` (`3 days ago`, hover for the ISO value).
- Status renders as a `Badge` with the semantic colour, never a coloured dot alone.
- An empty list shows an empty state with the primary action, never a bare "No results".
- Loading shows `Skeleton` rows matching the real column count, not a spinner — the layout must
  not jump when data arrives.

## Forms

Full rules in `.claude/rules/forms.md`. The visual contract:

- `Field` > `FieldLabel` + control + `FieldError`, stacked with `gap-1`, fields separated by
  `mb-4`.
- Required fields mark the label with a trailing asterisk in `text-danger`.
- Helper text is `text-xs text-muted-foreground` below the control; an error replaces it in
  `text-danger` and the control takes `border-danger` with a matching focus ring.
- Controls are `px-4 py-2 rounded-md` with a `ring-1 ring-ring` focus state. Compact is
  `px-3 py-1.5 text-sm`.
- Submit row is right-aligned, primary action last, `gap-2`. A pending submit disables the
  button and shows a spinner inside it — never a full-page overlay.
- Never style a bare `input`, `select`, `textarea`, or `label` element. Styling is opt-in through
  the component, so a third-party widget's markup is never accidentally restyled.

## Icons

`lucide-react`, the shadcn default. `size-4` inline with text, `size-5` standalone in a button.
Icons are decorative: every icon-only control needs an `aria-label`, and an icon never carries
meaning a colour or label doesn't also carry.

## Feedback

| Situation | Surface |
| --- | --- |
| Mutation succeeded | `sonner` toast, brief, no title |
| Mutation failed with field errors | inline `FieldError` per field, no banner |
| Mutation failed with no field errors | form-level `Alert` in `danger` |
| Destructive confirmation | `ConfirmDialog`, action button in `destructive` |
| Long-running job (clone, index, generate) | inline status with `Progress`, never a blocking modal — ingestion takes minutes |
| Permission denied on a route | `<Forbidden />`, not a redirect |

Ingestion and generation are slow by nature. Their feedback is always non-blocking and always
resumable on reload, because the operator will navigate away.

---

## See also

- [`README.md`](README.md) — the documentation index
- [`codebase.md`](codebase.md) — the frontend layout and the BFF split
- [`../.claude/rules/design-system.md`](../.claude/rules/design-system.md) — the enforceable rules behind this page
- [`../.claude/rules/forms.md`](../.claude/rules/forms.md) — dialog vs page, validation ownership
