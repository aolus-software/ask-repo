import { forwardedHeaders } from "@/lib/auth/forwarded";
import { apiUrl } from "@/lib/auth/session";

/**
 * Forward a public auth call — one that must work with no session at all.
 *
 * The generic API proxy answers 401 before forwarding when the browser holds no
 * cookie, which is correct everywhere except the few routes a signed-out user needs:
 * the password-reset trio and the password policy its form reads. Those get their
 * own `app/api/auth/*` files calling this. It attaches no bearer, relays the status
 * and body untouched, and — like every route except login/refresh/logout — never
 * sets a cookie.
 */
export async function forwardPublic(request: Request, path: string): Promise<Response> {
  const hasBody = request.method !== "GET" && request.method !== "HEAD";
  const upstream = await fetch(`${apiUrl()}${path}`, {
    method: request.method,
    headers: {
      ...(hasBody ? { "content-type": "application/json" } : {}),
      ...forwardedHeaders(request),
    },
    body: hasBody ? await request.text() : undefined,
    cache: "no-store",
  });

  const body = upstream.status === 204 ? null : await upstream.text();
  return new Response(body, {
    status: upstream.status,
    headers: body ? { "content-type": "application/json" } : {},
  });
}
