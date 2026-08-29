import { type NextRequest, NextResponse } from "next/server";

import {
  ACCESS_COOKIE,
  SESSION_COOKIE,
  SESSION_MAX_AGE_SECONDS,
  accessCookieMaxAge,
  cookieOptions,
} from "@/lib/auth/cookies";
import { type RefreshResult, apiUrl, refreshSession } from "@/lib/auth/session";

/**
 * The one route the browser talks to. It attaches the access token from the httpOnly
 * cookie, refreshes once on a 401, retries once, and streams the answer back.
 *
 * The path is joined onto a fixed API_URL, so this is a token-attaching forwarder,
 * not an open proxy — it cannot be pointed at another host.
 */

interface RouteContext {
  params: Promise<{ path: string[] }>;
}

/** Hop-by-hop and identity headers that must not be replayed upstream. */
const STRIPPED_REQUEST_HEADERS = new Set([
  "host",
  "connection",
  "cookie",
  "authorization",
  "content-length",
]);

/** Headers the runtime owns; forwarding them corrupts the response. */
const STRIPPED_RESPONSE_HEADERS = new Set([
  "content-encoding",
  "content-length",
  "transfer-encoding",
  "connection",
  // The backend rotates its own refresh cookie. Passed through, the browser would
  // hold a second refresh cookie that nothing reads and nothing rotates — and which
  // would eventually be presented and trigger the replay revocation.
  "set-cookie",
]);

async function handle(request: NextRequest, context: RouteContext): Promise<Response> {
  const { path } = await context.params;
  const target = `${apiUrl()}/${path.join("/")}${request.nextUrl.search}`;

  const sessionCookie = request.cookies.get(SESSION_COOKIE)?.value;
  let accessToken = request.cookies.get(ACCESS_COOKIE)?.value;
  let refreshed: RefreshResult | null = null;

  if (!accessToken) {
    if (!sessionCookie) return unauthenticated();
    refreshed = await refreshSession(sessionCookie);
    if (!refreshed) return unauthenticated();
    accessToken = refreshed.accessToken;
  }

  // Read the body once — a NextRequest body cannot be consumed twice, and the retry
  // below needs it again.
  const body =
    request.method === "GET" || request.method === "HEAD"
      ? undefined
      : await request.arrayBuffer();

  let upstream = await forward(request, target, accessToken, body);

  // The 401 arrives with the status line, before any body is consumed. That is what
  // makes a retry safe on the SSE route too — a half-read stream cannot be replayed,
  // so a retry sited any later would be a bug for that one endpoint.
  if (upstream.status === 401 && sessionCookie) {
    refreshed = await refreshSession(sessionCookie);
    if (!refreshed) return unauthenticated();
    upstream = await forward(request, target, refreshed.accessToken, body);
    if (upstream.status === 401) return unauthenticated();
  }

  const headers = new Headers();
  upstream.headers.forEach((value, key) => {
    if (!STRIPPED_RESPONSE_HEADERS.has(key.toLowerCase())) headers.set(key, value);
  });

  // Body passed through untouched, so an SSE stream is never accumulated.
  const response = new NextResponse(upstream.body, {
    status: upstream.status,
    headers,
  });

  if (refreshed) {
    response.cookies.set(
      ACCESS_COOKIE,
      refreshed.accessToken,
      cookieOptions(accessCookieMaxAge(refreshed.expiresIn)),
    );
    response.cookies.set(
      SESSION_COOKIE,
      refreshed.sessionCookie,
      cookieOptions(SESSION_MAX_AGE_SECONDS),
    );
  }

  return response;
}

function forward(
  request: NextRequest,
  target: string,
  accessToken: string,
  body: ArrayBuffer | undefined,
): Promise<Response> {
  const headers: Record<string, string> = {};
  request.headers.forEach((value, key) => {
    if (!STRIPPED_REQUEST_HEADERS.has(key.toLowerCase())) headers[key] = value;
  });
  headers.authorization = `Bearer ${accessToken}`;

  return fetch(target, {
    method: request.method,
    headers,
    body,
    cache: "no-store",
    redirect: "manual",
    // Required by undici whenever a request carries a body.
    ...(body ? { duplex: "half" } : {}),
  } as RequestInit);
}

function unauthenticated(): NextResponse {
  const response = NextResponse.json(
    {
      detail: {
        code: "INVALID_TOKEN",
        message: "Your session has expired. Please log in again.",
      },
    },
    { status: 401 },
  );
  response.cookies.set(ACCESS_COOKIE, "", cookieOptions(0));
  response.cookies.set(SESSION_COOKIE, "", cookieOptions(0));
  return response;
}

export const GET = handle;
export const POST = handle;
export const PATCH = handle;
export const PUT = handle;
export const DELETE = handle;
