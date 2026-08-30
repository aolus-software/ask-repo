/**
 * Validate a `?next=` target before redirecting to it.
 *
 * An unvalidated next param is an open redirect, and it sits on the login page —
 * the one place a redirect is most useful to someone phishing an operator. Only a
 * single-slash absolute path is accepted; `//host` is protocol-relative and browsers
 * treat it as another origin.
 */
export function safeNext(value: string | null): string {
  if (!value) return "/";
  if (!value.startsWith("/")) return "/";
  if (value.startsWith("//")) return "/";
  return value;
}
