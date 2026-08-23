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

A request to "filter projects by the current user in the list endpoint" contradicts
`docs/PRD.md` §4.1: projects are deliberately shared instance-wide in phase 1, and read
scoping must go through the single access resolver rather than a route-level filter. The
correct response is not to implement it, and not to implement "half" of it — it is to say:
this looks like phase-2 RBAC arriving early; doing it in the route would put read scoping in
two places, which §2's phase-2 readiness goal exists to prevent; the compliant version changes
the resolver's body instead. Then wait.
