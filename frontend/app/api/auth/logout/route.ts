import { NextResponse } from "next/server";

import { endpoints } from "@/lib/api/endpoints";
import { ACCESS_COOKIE, SESSION_COOKIE, cookieOptions } from "@/lib/auth/cookies";
import { apiUrl } from "@/lib/auth/session";

/**
 * Log out of this device, or everywhere when the body carries `{all: true}`.
 *
 * Cookies are cleared regardless of what the backend answers: a logout that fails
 * server-side but leaves the browser holding a session is the worst outcome
 * available, so clearing locally always is the safe direction.
 */
export async function POST(request: Request): Promise<Response> {
  const { all } = await readBody(request);
  const cookieHeader = request.headers.get("cookie") ?? "";
  const sessionCookie = readCookie(cookieHeader, SESSION_COOKIE);
  const accessToken = readCookie(cookieHeader, ACCESS_COOKIE);

  try {
    if (all && accessToken) {
      await fetch(`${apiUrl()}${endpoints.auth.logoutAll}`, {
        method: "POST",
        headers: { authorization: `Bearer ${accessToken}` },
        cache: "no-store",
      });
    } else if (sessionCookie) {
      await fetch(`${apiUrl()}${endpoints.auth.logout}`, {
        method: "POST",
        headers: { cookie: sessionCookie },
        cache: "no-store",
      });
    }
  } catch {
    // Deliberately swallowed — the local clear below is what the operator needs.
  }

  const response = new NextResponse(null, { status: 204 });
  response.cookies.set(ACCESS_COOKIE, "", cookieOptions(0));
  response.cookies.set(SESSION_COOKIE, "", cookieOptions(0));
  return response;
}

async function readBody(request: Request): Promise<{ all: boolean }> {
  try {
    const body = (await request.json()) as { all?: unknown };
    return { all: body?.all === true };
  } catch {
    return { all: false };
  }
}

function readCookie(header: string, name: string): string | undefined {
  for (const part of header.split(";")) {
    const [key, ...rest] = part.trim().split("=");
    if (key === name) return decodeURIComponent(rest.join("="));
  }
  return undefined;
}
