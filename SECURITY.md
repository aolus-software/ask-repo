# Security Policy

## Reporting a vulnerability

**Do not open a public issue.** Report privately through
[GitHub Security Advisories](../../security/advisories/new), or by email to the maintainer.

Please include the version or commit, what an attacker can do, and the steps to reproduce
it. You'll get an acknowledgement within a few days. This is a small project maintained in
spare time — expect best-effort timelines, not an SLA.

## Supported versions

Pre-1.0; M0 and M1 shipped. Only `main` is supported; there are no maintained release branches yet.

## Threat model

AskRepo is designed to run **inside a private network, serving one organization's trusted,
authenticated developers**. That assumption is load-bearing, so it's worth stating what it
does and doesn't cover.

**In scope:**

- Server-side request forgery through the repository URL supplied at ingestion.
- Disclosure of stored repository credentials (PATs).
- Credential brute-forcing against the login endpoint.
- Privilege gaps in destructive operations — deleting or re-indexing something you
  shouldn't be able to.
- Leakage of one user's private conversations to another.
- Secrets appearing in logs, tracebacks, or API responses.

**Out of scope:**

- **Malicious authenticated users.** All users on an instance are assumed to be trusted
  colleagues. In phase 1 every user can read and query every project — that is intended
  behaviour, not a vulnerability. Per-project access control is phase 2.
- **Public internet exposure.** The instance has no self-service account flows and is not
  hardened for anonymous traffic. Do not publish it.
- **Multi-tenancy.** One instance serves one organization. There is no tenant isolation
  layer, and reports that two organizations can see each other's data on a shared instance
  describe a deployment mistake rather than a bug.
- Denial of service through resource exhaustion by an authenticated user, beyond the
  concurrency and size caps already documented.
- **Targeted lockout of one known colleague via the per-email login limit.** The per-email
  counter (10 failures/hour) counts only failed attempts and clears on success, which stops a
  legitimate user's own logins from ever spending their own budget — but it does not stop a
  deliberate attacker. `check_email` runs before authentication, so anyone who knows a
  colleague's address can spend the budget with ten wrong guesses and keep the real owner
  locked out for the rest of the hour, even with the correct password, at a cost of roughly ten
  requests an hour and no valid credential of their own. There is no workaround via an admin
  password reset — resetting a password does not clear the counter; it only expires on its own
  after the hour. Also keying this limit by IP is a larger design change than this milestone
  makes; it has been raised separately and is not part of M0.

See [`docs/PRD.md`](docs/PRD.md) §9 for the full reasoning.

## Notes for operators

A few properties are your responsibility, not the code's:

- **Keep the instance off the public internet.** VPN or Tailscale only.
- **Set a real `SECRET_KEY` and `PAT_ENCRYPTION_KEY`.** The defaults are development
  placeholders, and `PAT_ENCRYPTION_KEY` must be **the same value in the API and the
  worker** — the API encrypts stored tokens and the worker decrypts them to clone. A
  mismatch shows up as clones that fail to decrypt, not as a startup error.
- **Change the seeded admin passwords.** `superuser@example.com` and `admin@example.com`
  ship with an env-supplied initial password and `must_change_password` set — complete that
  change before letting anyone else in.
- **Back up the PAT encryption key separately from the database.** Backing them up together
  means one stolen backup yields both the ciphertext and the key.
- **Scope PATs narrowly.** Read-only, single repository. Because projects are shared
  instance-wide in phase 1, a PAT added to a project effectively grants every user on the
  instance the ability to ask questions about that repository's contents.
- **Don't publish the Postgres, Qdrant, Redis, Kafka, or Ollama ports.** The development
  Compose file publishes them to `localhost` for convenience; a production deployment
  should not. Redis and Kafka in particular ship with **no authentication at all** in the
  dev configuration — the Kafka listener is `PLAINTEXT` and anyone who can reach it can
  publish ingestion jobs, which means making the instance clone an arbitrary URL, or read
  the job stream. Kafka must never be reachable beyond the internal network.
- **Ollama runs no auth either.** It is an embedding backend on the internal network; treat
  reaching it as equivalent to reaching the worker. If you point `EMBEDDING_PROVIDER` at a
  hosted API instead, `EMBEDDING_API_KEY` becomes a secret to manage like the others.
- **The worker is a second process holding the same secrets.** It reads the database, the
  PAT encryption key, and Qdrant. Deploy it with the same care as the API — it is the
  component that actually fetches user-supplied URLs from inside your network (§9's SSRF
  discussion applies to the worker, not the API).
- **Set `BOOTSTRAP_ADMIN_PASSWORD` before first boot**, and change both seeded accounts
  immediately after. The seed command refuses to run without it rather than inventing a
  password, so a missing value fails the boot loudly instead of quietly creating a guessable
  admin.
- **TLS is required, not optional.** The refresh token is a `Secure` cookie, so a browser will
  not send it over plain HTTP outside `localhost`. Run Caddy in front.
- **Set `TRUSTED_PROXY_HOPS` to the number of proxies in front of the API** — one, with the
  Caddy setup above. It tells `client_ip()` how many entries to discard from the right of
  `X-Forwarded-For` before trusting what remains. Left at its default of `0` behind a proxy,
  every request's socket address is Caddy's, so the per-IP login limit — meant to be 5 attempts
  per minute per caller — becomes 5 attempts per minute for the entire organization, and because
  the limit is counted before the credential check, ordinary successful logins consume it too. A
  production boot with `TRUSTED_PROXY_HOPS` still at `0` is refused for exactly this reason
  (`app/config.py`).
- **A Redis outage degrades login rate limiting.** The limiter fails open by design — an outage
  should not lock the whole team out — so brute-force protection is reduced to bcrypt's cost
  while Redis is down.
