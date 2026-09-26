/**
 * The reset token rides in the URL fragment, never the query string: a browser never
 * sends a fragment to any server, so it stays out of Next's logs, a reverse proxy's
 * access log and any Referer header (spec §6.4). Callers pass `window.location.hash`.
 */
export function readResetToken(hash: string): string | null {
  const token = new URLSearchParams(hash.replace(/^#/, "")).get("token");
  return token ? token : null;
}
