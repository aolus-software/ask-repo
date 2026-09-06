# AskRepo documentation

Start here. Every page below is written to be read on its own, but they are ordered so that
reading straight down works too.

---

## Start with why

**[`PRD.md`](PRD.md)** — the product requirements. What AskRepo is for, who it serves, the access
model, the schemas, the security decisions, and the milestones.

> **This is the source of truth.** It outranks every other doc *and* outranks the code. When code
> and the PRD disagree, that is a contradiction to report, not a doc to quietly rewrite. It is
> also **the only place that records progress** — §6 says which milestones are built. No other
> document tracks that, which is why no other document can go stale about it.

---

## Understand the system

Read these in order the first time. Roughly two hours end to end.

| # | Page | Answers |
| --- | --- | --- |
| 1 | **[`architecture.md`](architecture.md)** | What runs where? Why is there a worker? Why four datastores? What happens, step by step, when someone asks a question or adds a repository? |
| 2 | **[`data.md`](data.md)** | Where does everything get stored? What are the 13 tables and how do they relate? Why does a delete reach into Qdrant? What is a lease? |
| 3 | **[`rag.md`](rag.md)** | How does a repository become searchable? What is chunking, embedding, a vector? How is the right code found for a question, and how do we know the answer is grounded in it? |
| 4 | **[`llm.md`](llm.md)** | Which model gets called, and how? How do we get structured data out of a model instead of prose? What stops a broken provider burning money or a retry ladder? |
| 5 | **[`langgraph.md`](langgraph.md)** | Why a graph instead of a chain? How does the self-critique loop work? How does an answer stream to the browser, and how is it saved if the user closes the tab? |
| 6 | **[`codebase.md`](codebase.md)** | Where does code live? What are the layers? **Where do I put the thing I am about to write?** |

---

## Get it running

| Page | Use it when |
| --- | --- |
| **[`installation.md`](installation.md)** | Setting up locally. Three paths — everything in Docker, datastores only in Docker, or no `make` at all — plus first login and troubleshooting |
| **[`configuration.md`](configuration.md)** | Any question about a setting. All 71 backend settings, the frontend variable, and the Compose `.env`, each with what it does and what to change before production |
| **[`deployment.md`](deployment.md)** | Running it for a team. Production images, TLS with Caddy, secrets, first boot, backups |

---

## Build on it

| Page | Use it when |
| --- | --- |
| **[`design.md`](design.md)** | Writing any UI. Tokens, typography, layout geometry, spacing, the component inventory |
| **[`codebase.md`](codebase.md)** | Adding a route, a table, a setting, a screen, or a background job |
| **[`../.claude/rules/`](../.claude/rules/)** | 13 rule files with the precise convention for each area — routers, persistence, RAG, ingestion, forms, navigation, the frontend BFF. Written for coding agents, but the most exact statement of each rule |

---

## Reading paths

**"I just joined and I am picking up a ticket."**
[`PRD.md`](PRD.md) §1–§4 → [`architecture.md`](architecture.md) → [`codebase.md`](codebase.md) →
the rule file for the area you are touching.

**"I need to run this."**
[`installation.md`](installation.md) → [`configuration.md`](configuration.md) →
[`deployment.md`](deployment.md).

**"I want to understand the AI parts."**
[`rag.md`](rag.md) → [`llm.md`](llm.md) → [`langgraph.md`](langgraph.md). Then read
`backend/app/rag/prompts.py` — the prompts are short and they are where behaviour actually lives.

**"Answers are wrong or low quality."**
[`rag.md`](rag.md) "Four rules that fail silently" → [`configuration.md`](configuration.md)
"Values that fail silently" → run `uv run pytest -m model`.

**"Something is stuck in the queue."**
[`architecture.md`](architecture.md) "The job queue" → [`data.md`](data.md) "The lease is the
deduplication boundary" → `.claude/rules/ingestion.md`.

---

## Also worth knowing

- **[`../backend/README.md`](../backend/README.md)** — the exhaustive route table (55 routes), the
  backend layout, and dev commands.
- **[`../frontend/README.md`](../frontend/README.md)** — frontend scripts, env, and the BFF layout.
- **[`../CLAUDE.md`](../CLAUDE.md)** — the invariants a coding agent must not break. It states
  rules; these docs explain mechanisms.
- **[`../SECURITY.md`](../SECURITY.md)** — the threat model, and what an operator is responsible
  for.
- **[`../CONTRIBUTING.md`](../CONTRIBUTING.md)** — conventions, check commands, and what is out of
  scope.

---

## A note on keeping these honest

If your change makes a page here wrong, fixing it is **part of the same change** — see
`.claude/rules/documentation.md`. Two specifics that are easy to miss:

- A new `Settings` field lands in `app/config.py`, `backend/.env.example`, **and**
  [`configuration.md`](configuration.md) together.
- **Do not add a status banner, roadmap, or "shipped" claim to any page here.** Progress lives in
  [`PRD.md`](PRD.md) §6 and nowhere else.
