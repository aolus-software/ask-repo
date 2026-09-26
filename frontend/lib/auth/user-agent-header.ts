/**
 * Relaying the browser's user agent to the backend, on login only.
 *
 * The login call leaves from the Next server, so without this every session records
 * Node's own agent string and the profile's session list cannot tell a phone from a
 * laptop. Only login needs it: the backend copies a session's device forward on every
 * rotation, because a refresh arrives from here and not from the browser.
 */
export function userAgentHeader(request: Request): Record<string, string> {
  const userAgent = request.headers.get("user-agent");
  return userAgent ? { "user-agent": userAgent } : {};
}
