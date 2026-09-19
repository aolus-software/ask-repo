/**
 * Relaying the caller's address to the backend.
 *
 * Every backend request leaves from the Next server, so without this the backend sees
 * one socket address for the whole organization: the per-caller login limit becomes a
 * single instance-wide bucket of five attempts a minute, and every audit row records
 * the Next server rather than the person (issue #40).
 *
 * The header is **relayed, never rewritten**. Next cannot see its own socket peer from
 * a route handler, so it has no address of its own to append — and appending nothing is
 * what keeps `TRUSTED_PROXY_HOPS` meaning "how many proxies append an entry". One Caddy
 * is still `1`, with Next in between, and `docs/deployment.md` says so.
 *
 * Relaying a header the browser controls is safe because of how the backend reads it:
 * `client_ip` counts from the **right**, discarding one entry per trusted hop, so a
 * forged entry a client prepends is discarded along with everything left of the real
 * one. With no proxy in front (`TRUSTED_PROXY_HOPS=0`) the backend ignores the header
 * outright.
 *
 * With nothing in front of Next there is no header to relay and nothing to do: the
 * address is unavailable, which is the development shape and why the dev stack leaves
 * the hop count at `0`.
 */
export function forwardedHeaders(request: Request): Record<string, string> {
  const forwardedFor = request.headers.get("x-forwarded-for");
  return forwardedFor ? { "x-forwarded-for": forwardedFor } : {};
}
