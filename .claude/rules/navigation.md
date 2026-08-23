---
paths:
  - "frontend/**/*.tsx"
  - "frontend/lib/**/*.ts"
---

# Navigation Rules

## 1. One source of truth

`lib/nav.ts` is the only place destinations are declared. The sidebar and the breadcrumbs both
read it, so they cannot drift. A group's children are declared in one module of their own
(`lib/settings-nav.ts` for Settings), and `lib/nav-child.ts` holds the shared `NavChild` shape.

That split is load-bearing, not tidiness: `nav.ts` imports each group's list as a **value**, so a
group module importing the type back from `nav.ts` would close an import cycle. A leaf module
both sides depend on keeps the graph one-way.

**Never hardcode a nav label or href in a component.**

## 2. The sidebar renders a tree and computes nothing

`visibleNavTree(user)` in `lib/nav.ts` returns the items this operator can reach, children
already resolved and filtered. It is pure, so the filtering is tested without React.
`components/layout/app-sidebar.tsx` is a thin renderer over that tree.

`children` is **present only on a group**, never an empty array on a leaf: the sidebar renders a
link when it is absent and a collapsible group when it is not, which is one check rather than a
length test plus a special case per group.

## 3. Sub-navigation is a collapsible sidebar group

Not in-page tabs. A destination with children renders as a `Collapsible` whose trigger is the
parent row and whose panel holds `SidebarMenuSub` child links.

- The parent row is a **trigger, not a link**. A group's index route only redirects to its first
  reachable child, so making it navigable adds a hop that ends where the expanded list already is.
- A group's routes are **nested under its own href** (`/settings/users`, not `/users`). Active
  detection compares prefixes, the index route needs somewhere to redirect, and breadcrumbs
  resolve a trail by longest matching nav item — all three depend on that prefix being real.
- It opens **already expanded** when the current route is inside it, so a deep link lands with
  its section visible.
- A group whose children are all unreachable is **hidden entirely**. A group that opens onto
  nothing is broken UI.

## 4. Gate nav items in the config, not the component

A `NavItem` carries an optional `adminOnly` flag. Phase 1 has exactly one axis of authority —
`is_admin` — so that is a boolean, not a permission string. Do not invent a permission system in
the frontend ahead of the backend having one.

While the profile request is pending the sidebar renders placeholder rows, **never a filtered
list**. Showing a short menu that then grows is the visible form of a permission flash.

> **Phase 2 will add per-project access** (`docs/PRD.md` §2.1). When it does, `adminOnly` becomes
> a richer predicate in this same config, and no component changes. Keep the gate declarative for
> that reason.

## 5. Breadcrumbs: separator is a sibling, never a child

`BreadcrumbItem` and `BreadcrumbSeparator` **both render an `<li>`**. Nesting the separator
inside the item is invalid HTML and fails hydration in the browser while passing every render
assertion. Wrap each pair in a `Fragment` and emit the separator beside the item:

```tsx
<Fragment key={crumb.href}>
	<BreadcrumbItem>…</BreadcrumbItem>
	{isLast ? null : <BreadcrumbSeparator />}
</Fragment>
```

## 6. Route shape for a resource

```
/<group>/<resource>            list
/<group>/<resource>/[id]       detail (when the resource is read-only)
/<group>/<resource>/new        create form (when it is a page)
/<group>/<resource>/[id]/edit  edit form (when it is a page)
```

A read-only resource has a list and a detail and nothing else.

The shape AskRepo is heading for:

```
/                       dashboard
/projects               list + create dialog
/projects/[id]          detail: status, stats, reindex, delete
/ask                    Dev Knowledge — project picker + conversation
/ask/[conversationId]   a conversation (private to the operator)
/qa                     QA List (shared)
/qa/[id]/edit           edit a QA pair
/settings/users         admin only
```

Notes that bite:

- A list screen reads `useSearchParams()`, so its `page.tsx` stays a Server Component wrapping
  the client screen in `<Suspense>` — without it `next build` fails on that route.
- `params` is async in Next 16 and is **always awaited**.
- Every route body is wrapped in its gate. **Hiding the nav item is not gating the route** — an
  operator can type the URL.

## 7. Conversations are private; projects are not

`/projects` and `/qa` show everything on the instance — that is intended (`docs/PRD.md` §4.1).
`/ask/[conversationId]` shows only the operator's own, and a foreign id answers `404`, not `403`
(`response-api.md`). The nav must not imply otherwise: there is no "all conversations"
destination, and the conversation list in the sidebar or picker is always the caller's own.
