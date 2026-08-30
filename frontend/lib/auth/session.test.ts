import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  __resetRefreshFlight,
  extractSessionCookie,
  refreshSession,
} from "@/lib/auth/session";

const ORIGINAL_API_URL = process.env.API_URL;

beforeEach(() => {
  process.env.API_URL = "http://backend:8000";
  __resetRefreshFlight();
});

afterEach(() => {
  process.env.API_URL = ORIGINAL_API_URL;
});

function refreshOk(): Response {
  const body = JSON.stringify({
    accessToken: "new-access",
    tokenType: "bearer",
    expiresIn: 900,
    user: { id: "u1" },
  });
  return new Response(body, {
    status: 200,
    headers: {
      "content-type": "application/json",
      "set-cookie":
        "askrepo_refresh=rotated; Path=/auth; HttpOnly; Secure; SameSite=lax",
    },
  });
}

describe("extractSessionCookie", () => {
  it("captures the name=value pair verbatim, whatever the cookie is called", () => {
    const response = new Response(null, {
      headers: { "set-cookie": "some_other_name=abc123; Path=/auth; HttpOnly" },
    });
    expect(extractSessionCookie(response)).toBe("some_other_name=abc123");
  });

  it("returns null when the backend set no cookie", () => {
    expect(extractSessionCookie(new Response(null))).toBeNull();
  });
});

describe("refreshSession", () => {
  it("returns the new token and the rotated session cookie", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => refreshOk()),
    );
    const result = await refreshSession("askrepo_refresh=old");
    expect(result).not.toBeNull();
    expect(result?.accessToken).toBe("new-access");
    expect(result?.expiresIn).toBe(900);
    expect(result?.sessionCookie).toBe("askrepo_refresh=rotated");
  });

  it("sends the stored pair back verbatim as a Cookie header", async () => {
    const spy = vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(
      async () => refreshOk(),
    );
    vi.stubGlobal("fetch", spy);
    await refreshSession("askrepo_refresh=old");
    const init = spy.mock.calls[0]?.[1] as RequestInit;
    expect((init.headers as Record<string, string>).cookie).toBe("askrepo_refresh=old");
  });

  it("returns null when the backend refuses", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(null, { status: 401 })),
    );
    expect(await refreshSession("askrepo_refresh=dead")).toBeNull();
  });

  it("returns null when the backend returns a 200 with a literal JSON null body", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response("null", {
            status: 200,
            headers: { "content-type": "application/json" },
          }),
      ),
    );
    expect(await refreshSession("askrepo_refresh=old")).toBeNull();
  });

  it("returns null when the backend is unreachable", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("fetch failed");
      }),
    );
    expect(await refreshSession("askrepo_refresh=old")).toBeNull();
  });

  it("makes ONE backend call for two concurrent refreshes", async () => {
    const spy = vi.fn(
      async () =>
        new Promise<Response>((resolve) => setTimeout(() => resolve(refreshOk()), 10)),
    );
    vi.stubGlobal("fetch", spy);

    const [a, b] = await Promise.all([
      refreshSession("askrepo_refresh=old"),
      refreshSession("askrepo_refresh=old"),
    ]);

    expect(spy).toHaveBeenCalledTimes(1);
    expect(a?.accessToken).toBe("new-access");
    expect(b?.accessToken).toBe("new-access");
  });

  it("allows a fresh refresh after the in-flight one settles", async () => {
    const spy = vi.fn(async () => refreshOk());
    vi.stubGlobal("fetch", spy);
    await refreshSession("askrepo_refresh=old");
    await refreshSession("askrepo_refresh=rotated");
    expect(spy).toHaveBeenCalledTimes(2);
  });
});
