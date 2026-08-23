# Documentation Upkeep Rule

## Principle: docs are part of the change, not an afterthought

When a change makes a documentation file wrong, fixing that doc is part of the **same
change** — not a follow-up and not "later". Code and docs are committed together so the
repository never carries documentation that contradicts the code.

This is not a mandate to rewrite docs on every commit. It is: **if you changed something a doc
describes, update that doc in the same change.** If nothing a doc covers changed, leave it
alone.

## Docs that must stay in sync

| Doc | Update it when… |
| --- | --- |
| `docs/PRD.md` | scope, a feature's intended behaviour, a schema, the access model, a milestone, or a security decision changes. This is the source of truth — it is wrong last, not first |
| `README.md` (root) | setup, the quick-start commands, the service/port table, the stack, the repo layout, or the roadmap checkboxes change |
| `backend/README.md` | a route is added/changed/removed, a config value changes, the layout changes, or a dev command changes. The route table must be exhaustive |
| `frontend/README.md` | scripts, env vars, or the app layout change |
| `backend/.env.example` | **any** new or renamed `Settings` field in `app/config.py`. A setting with no example entry is undiscoverable |
| `frontend/.env.example` | any new `NEXT_PUBLIC_*` variable |
| `infra/docker-compose.yml` header comment | a service is added/removed, or a published port changes — the URL list at the top must match the services below |
| `SECURITY.md` | the threat model changes, or a new operator responsibility appears (a new secret, a new published port) |
| `CONTRIBUTING.md` | a convention, a check command, or the out-of-scope list changes |
| `CLAUDE.md` | a rule file is added/renamed/deleted, the layout changes, or a stated fact (commands, milestone, route list) goes stale. **Keep counts exact** |
| `.claude/rules/*.md` | a coded convention changes, or a new pattern ships with no rule yet — add one |

## What "up to date" means

- **Exact facts:** counts (rule files, routes, services), paths, model/field names, env var
  names, and commands must match reality. A stale count or a renamed helper is a documentation
  bug.
- **No orphan references:** if you rename, move, or delete a file, function, or rule, update
  every doc that names it. Do not leave links to things that no longer exist.
- **Status honesty:** a roadmap checkbox for a shipped milestone must be ticked; a "planned"
  feature that shipped must be described as shipped. The `README.md` status banner ("Status:
  pre-M0") is a claim about the code and must be corrected when it stops being true.
- **New surfaces get docs:** a new route group, background job, external integration, or
  module that establishes a pattern needs its doc or rule created, not just its code.
- **Examples must be real.** A `curl` in a README must actually work against the code as
  committed. A response example must match what the endpoint returns — see `response-api.md`.

## The PRD is the source of truth

`docs/PRD.md` outranks every other doc. When code and the PRD disagree, that is a
contradiction to report (`contradiction-halt.md`), not a doc to quietly rewrite to match the
code. When the user decides the code is right, update the PRD in that same change and say so.

## When a doc is wrong but the current task didn't cause it

Per `contradiction-halt.md`, if you notice a doc contradicts the code but fixing it is outside
the requested task, **report it to the user** — do not silently rewrite unrelated docs. The
"update in the same change" duty covers docs your own change affects.
