---
paths:
  - "frontend/**/*.tsx"
  - "frontend/**/*.css"
---

# Design system rules

These rules are enforced. `docs/design.md` is the reference they point at.

## 1. Never hand-roll a component shadcn provides

Add it with the CLI: `npx shadcn@latest add <name>`. Search first —
`npx shadcn@latest search @shadcn -q "<thing>"`. Never create a file in
`components/ui/` by hand; that directory is CLI-managed, and keeping it untouched is what makes
an upstream diff readable.

`docs/design.md` → "Component inventory" lists the intended set per surface. Install the row
you need when you need it; do not install the whole table up front.

## 2. No raw colour, radius, or font value in a component

Every colour and radius exists as a token. A raw hex, `rgb()`, `oklch()`, or a literal `px`
radius in a component is a bug.

- Wrong: `className="bg-[#615fff] rounded-[10px]"`
- Right: `className="bg-primary rounded-md"`

**`frontend/app/globals.css` is the only file permitted to contain a raw hex colour**, with one
exception that cannot be otherwise: `frontend/app/manifest.ts`'s `theme_color` and
`background_color`. The browser reads those to paint its own chrome before any stylesheet loads,
so they cannot be tokens. They are kept as literal mirrors of `--primary` and `--background`, and
the file says so — change one and you change both.

Palette utilities count as raw values too. `bg-zinc-50`, `text-slate-600`, and `border-gray-200`
name a colour rather than a role, so they do not change with the theme:

- Wrong: `className="bg-white text-zinc-600 border-gray-200"`
- Right: `className="bg-card text-muted-foreground border-border"`

## 3. All colour flows through the token, and dark mode is never written in a component

This is the rule the reference repos disagree on, and the resolution is deliberate. Tokens are
defined once per role and **redefined under `.dark`**. A component states the role and gets both
themes for free.

```tsx
// WRONG — a manual dark override. Two places to keep in sync, and a missed one
// is invisible until someone toggles the theme.
<div className="bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-100">

// CORRECT — the token already knows what dark means
<div className="bg-card text-card-foreground">
```

**Never write a `dark:` colour utility in a component.** If a surface needs a dark treatment
that no token provides, the fix is a new token in `globals.css`, not an override at the call
site. `dark:` remains legal for non-colour properties (`dark:invert` on a logo, for instance).

## 4. Pair every background with its `-foreground`

`bg-primary` takes `text-primary-foreground`. `bg-card` takes `text-card-foreground`. Never
`text-white` on a coloured surface — white becomes wrong the moment the token moves, and it is
already wrong in dark mode where `primary-foreground` is near-black.

## 5. Status colour is semantic and mapped in one place

A project's `status`, a QA pair's `verified` flag, and a job's outcome map to
`success` / `warning` / `danger` / `info` through a single helper. Never pick a colour per
component — a badge, a table row, and a detail header showing the same state must agree.

## 6. `docs/design.md` and the tokens change together

A token edit that does not update `docs/design.md` in the same commit is incomplete. The token
table in that document is a fact about `globals.css`, and a stale fact is a documentation bug —
see `documentation.md`.

## 7. Base UI composition — always `render`, never `asChild`

This project uses shadcn's **Base UI** base. To swap the rendered element, pass
**`render={<Component />}`**:

```tsx
<SidebarMenuButton render={<Link href="/projects" />}>Projects</SidebarMenuButton>
<BreadcrumbLink render={<Link href={crumb.href} />}>{crumb.label}</BreadcrumbLink>
<DropdownMenuTrigger render={<Button variant="ghost" />}>Menu</DropdownMenuTrigger>
```

**`asChild` does not exist in this project.** Components generated into `components/ui/` are
built on `useRender` from `@base-ui/react/use-render` and expose a `render` prop. Passing
`asChild` fails silently — the prop is ignored and your element never renders.

The published shadcn docs on the web still show `asChild` examples. **Trust the generated source
in `components/ui/`, not the website.** Verify with
`grep -rn "asChild\|useRender" components/ui/<component>.tsx`.

## 8. Never style a bare form element

Styling is opt-in through the component. A bare `input`, `select`, `textarea`, or `label`
selector in CSS silently restyles every third-party widget's internal markup — a date picker, a
rich-text editor, a file dropzone — and the breakage appears far from the rule that caused it.

## 9. Layout geometry is fixed

Navbar `h-16`, sidebar `w-64`, content `mt-16 p-4 md:p-8` (`docs/design.md` → Layout). The
`4rem` navbar height is load-bearing: the sidebar's `top` and its `h-[calc(100vh-4rem)]` both
derive from it. Changing one without the others produces a sidebar that scrolls under the navbar
or leaves a gap at the bottom.

## 10. Spacing comes from the documented intervals

`1, 2, 3, 4, 6, 8, 12` only. An arbitrary `p-5` or `gap-7` in one component is how a layout
starts looking hand-tuned. The per-context table in `docs/design.md` → Spacing is the default;
deviate only with a reason worth a comment.

## 11. A `<Table>` always sits inside a `Card`

No exceptions, including a grid on a detail-page tab that is not one of the four-part list
screens `docs/design.md` → Lists describes. A bare `<Table>` shows the page's `bg-background`
through it instead of `bg-card`, which reads as a different, less-finished surface from every
other table in the app — this is exactly how the checklist grid on `/checklist/[moduleId]`
drifted from `/projects`, `/settings/users`, and `/checklist` (`docs/ui-audit-findings.md`).

`<Card className="p-0">` wraps the table; a horizontal-scroll container, if the table needs
one, nests **inside** that Card rather than being applied to the Card itself — Card's own
`overflow-hidden` and an `overflow-x-auto` on the same element fight each other, and which one
wins depends on Tailwind's generated stylesheet order, not on which class was written last in
the component.
