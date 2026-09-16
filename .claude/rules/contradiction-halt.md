# Contradiction Halt Rule

## Principle: the request can be wrong — surface it, don't silently "fix" it

The user (or a task, plan, or issue) may ask for something that contradicts these rules, the
documented architecture, or that would introduce a bug. **The user may be wrong, and that is
expected.** When you detect such a contradiction, **stop and tell the user, and do nothing
else about it** until they decide.

This applies whether the contradiction is with:

- a rule in `.claude/rules/*.md` or `CLAUDE.md`,
- `docs/PRD.md` — the source of truth for scope, schemas, and access model,
- the documented architecture or an existing pattern in the codebase,
- an actual latent bug the requested change would create or depend on, or
- a security/access invariant: the access resolver, `created_by` gating, `is_admin`,
  conversation privacy, soft-delete-vs-Qdrant, or clone-URL validation.

## What "do nothing" means

- **Do not implement the contradicting change**, not even a "best-guess" partial version.
- **Do not silently work around it** or quietly pick a different approach without saying so.
- **Do not fix the contradicting bug on your own initiative** as part of an unrelated task —
  report it and wait.

## What to do instead

1. State the contradiction plainly: what was requested, which rule/doc/invariant it conflicts
   with (cite the rule file or `file:line`), and the concrete consequence — bug, data leak,
   broken contract, inconsistency.
2. If you have a compliant alternative, offer it as a recommendation — but still wait for the
   user to choose.
3. Proceed only after the user explicitly confirms. If they confirm the original request
   knowing the trade-off, that is their call to make.
4. **If the decision changes a documented fact, update the doc in the same change** — see
   `documentation.md`. A resolved contradiction that leaves the PRD saying the old thing has
   just moved the contradiction rather than settled it.

## Scope

- This is a **halt-and-report** rule, not permission to refuse work. Once the user
  acknowledges the contradiction and decides, follow their decision.
- It does **not** apply to trivial style nits you can just conform to — match the surrounding
  code and move on. It applies to genuine contradictions with rules, architecture, security,
  or correctness.
- Audits (`/audit-flow`) are report-only by definition; this rule reinforces that findings are
  reported, never acted on, unless the user asks.

## Worked example

A request to "only show people the projects they created — add a `created_by == user.id`
filter to the list endpoint" contradicts two things at once. `docs/PRD.md` §7 says
`created_by` is **attribution** and must never scope reads; and §2's single-resolver goal says
read scoping happens in exactly one function, `resolve_project_scope` in `app/core/access.py`,
which `tests/test_scoping_is_single_point.py` enforces as a grep.

The correct response is not to implement it, and not to implement "half" of it — it is to say:
reads are already scoped, and they are scoped to **membership**, not authorship, so a creator
who was removed from a project would still see it and a colleague who was granted `owner` would
not. Adding the filter in the route also puts read scoping in two places, which is the failure
§2 exists to prevent — a later change to the resolver would then silently not apply here. If
what is actually wanted is a *non-access* filter over the same list (the way `?ownerless=true`
works), the compliant shape is `ProjectScope.narrowed_to(...)` on top of the resolver's answer,
never in place of it. Then wait for the user to choose.
