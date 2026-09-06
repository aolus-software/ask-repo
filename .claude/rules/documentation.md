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
| `docs/PRD.md` | scope, a feature's intended behaviour, a schema, the access model, a milestone, **milestone progress**, or a security decision changes. This is the source of truth, and the only doc that records progress — it is wrong last, not first |
| `README.md` (root) | setup, the quick-start commands, the service/port table, the stack, the repo layout, or the roadmap checkboxes change |
| `backend/README.md` | a route is added/changed/removed, a config value changes, the layout changes, or a dev command changes. The route table must be exhaustive |
| `frontend/README.md` | scripts, env vars, or the app layout change |
| `docs/installation.md` | a setup step, a `make` target used in setup, a prerequisite version, or a first-boot behaviour changes |
| `docs/deployment.md` | the Dockerfiles, the Compose topology, a production-only setting, or an operator obligation changes |
| `docs/README.md` | a doc is added to `docs/`, or the reading order changes. It is the index readers land on |
| `docs/architecture.md` | a process, datastore, or request lifecycle changes |
| `docs/codebase.md` | the layering changes, a package is added/removed, or a count in its tree goes stale |
| `docs/data.md` | a table, migration, lease, or storage rule changes |
| `docs/rag.md` | chunking, embedding, collection naming, retrieval filtering, or grounding changes |
| `docs/llm.md` | a chat provider, the structured-output path, the retry taxonomy, or a spend bound changes |
| `docs/langgraph.md` | a graph node, an edge, the SSE event set, or the shielded write changes |
| `docs/configuration.md` | **any** new, renamed, or re-defaulted `Settings` field, or a new `infra/.env` variable. This is where a setting's meaning lives — the `.env.example` files carry names and defaults only |
| `backend/.env.example` | **any** new or renamed `Settings` field in `app/config.py`, in its group, with the same default and no inline prose. A setting with no example entry is undiscoverable |
| `frontend/.env.example` | any new frontend environment variable. There are no `NEXT_PUBLIC_*` variables any more — `API_URL` is read server-side, and re-adding the prefix would inline it into the client bundle |
| `infra/docker-compose.yml` header comment | a service is added/removed, or a published port changes — the URL list at the top must match the services below |
| `infra/docker-compose.prod.yml` | any change to the development compose file that is not development-specific. The two drift silently — nothing builds or starts the production stack during `make check` |
| `CHANGELOG.md` | a user-visible change lands: a route, a JSON field, an `ErrorCode`, a default, or a fixed defect. Add it under `## [Unreleased]`, not to a released section — released sections are a historical record and are never edited |
| `SECURITY.md` | the threat model changes, or a new operator responsibility appears (a new secret, a new published port) |
| `CONTRIBUTING.md` | a convention, a check command, or the out-of-scope list changes |
| `CLAUDE.md` | a rule file is added/renamed/deleted, the layout changes, or a stated fact (commands, route list, module map) goes stale. **Keep counts exact**, and keep milestone status out |
| `.claude/rules/*.md` | a coded convention changes, or a new pattern ships with no rule yet — add one |

## What "up to date" means

- **Exact facts:** counts (rule files, routes, services), paths, model/field names, env var
  names, and commands must match reality. A stale count or a renamed helper is a documentation
  bug.
- **No orphan references:** if you rename, move, or delete a file, function, or rule, update
  every doc that names it. Do not leave links to things that no longer exist.
- **Progress lives in the PRD, and only there.** `docs/PRD.md` §6 is the single record of which
  milestones are built. No other doc carries a status banner, a roadmap with checkboxes, or an
  "M4 is shipped" claim — **do not add one back**, and if you find one, remove it and point at
  §6 instead. Every other doc describes what is in the tree in the present tense, which is a
  different question from how far along the project is and does not go stale when a milestone
  lands. Avoid hardcoding a milestone *range* (`M0–M5`) anywhere outside the PRD: it is wrong
  the moment the list changes.
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
