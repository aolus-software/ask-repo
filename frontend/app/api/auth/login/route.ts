import { NextResponse } from "next/server";

import { endpoints } from "@/lib/api/endpoints";
import {
  ACCESS_COOKIE,
  SESSION_COOKIE,
  SESSION_MAX_AGE_SECONDS,
  accessCookieMaxAge,
  cookieOptions,
} from "@/lib/auth/cookies";
import { apiUrl, extractSessionCookie } from "@/lib/auth/session";

/**
 * Exchange credentials for a session Next holds on the operator's behalf.
 *
 * The access token is set as an httpOnly cookie and deliberately omitted from the
 * response body — that omission is the entire point of the BFF (design spec §2.1).
 */
export async function POST(request: Request): Promise<Response> {
  const body = await request.text();

  const upstream = await fetch(`${apiUrl()}${endpoints.auth.login}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body,
    cache: "no-store",
  });

  // Failures pass through intact: the form must tell INVALID_CREDENTIALS from RATE_LIMITED.
  if (!upstream.ok) {
    return new NextResponse(await upstream.text(), {
      status: upstream.status,
      headers: { "content-type": "application/json" },
    });
  }

  const payload = (await upstream.json()) as {
    accessToken: string;
    expiresIn: number;
    user: unknown;
  };
  const sessionCookie = extractSessionCookie(upstream);

  if (!sessionCookie) {
    // No refresh cookie means a session that dies in 15 minutes with no way to renew.
    return NextResponse.json(
      {
        detail: {
          code: "INTERNAL_ERROR",
          message: "The server did not start a session.",
        },
      },
      { status: 502 },
    );
  }

  const response = NextResponse.json({ user: payload.user });
  response.cookies.set(
    ACCESS_COOKIE,
    payload.accessToken,
    cookieOptions(accessCookieMaxAge(payload.expiresIn)),
  );
  response.cookies.set(
    SESSION_COOKIE,
    sessionCookie,
    cookieOptions(SESSION_MAX_AGE_SECONDS),
  );
  return response;
}
