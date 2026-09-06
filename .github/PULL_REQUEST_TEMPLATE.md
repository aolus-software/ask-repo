# Summary

<!-- What changes, and why. One or two sentences. -->

Closes #

## Type of change

- [ ] Bug fix
- [ ] Feature
- [ ] Refactor (no behaviour change)
- [ ] Infra / tooling
- [ ] Docs

## Milestone

<!-- Which PRD milestone does this serve? Or "none". The list is in docs/PRD.md §6. -->

## What changed

<!--
Walk a reviewer through it. Note anything non-obvious: a decision you made, a
tradeoff you took, or a place you'd like a second opinion.
-->

## How this was verified

<!--
Not "it should work" — what you actually ran, and what it printed. Paste the
command and the relevant output.
-->

```
```

- [ ] `uv run pytest` passes (backend changes)
- [ ] `uv run ruff check .` clean (backend changes)
- [ ] `bun lint` clean (frontend changes)
- [ ] `docker compose config` valid (infra changes)
- [ ] Manually exercised the affected route(s)

## Checklist

- [ ] Docs updated — `docs/PRD.md` if behaviour or scope changed, the relevant `README.md` if setup did
- [ ] `.env.example` updated if a new config value was added
- [ ] Migration included if the schema changed
- [ ] No secrets, tokens, or real credentials in the diff — including in test fixtures
- [ ] New config values documented, not just defaulted

## Security and access

<!-- Delete this section if the change touches none of it. -->

- [ ] Read scoping still goes through the single access resolver — no route filters projects on its own (PRD §4.1, §5.1)
- [ ] Destructive operations still gated on `created_by` or `is_admin`
- [ ] Correct error codes: `403` for "may see but not do", `404` for "may not know it exists" (PRD §5.1)
- [ ] No secret is logged, returned, or included in a traceback
- [ ] Any new user-supplied URL is validated per PRD §9 (scheme, host allowlist, private-address rejection)
