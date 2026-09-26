import { afterEach, describe, expect, it, vi } from "vitest";

import { forwardPublic } from "@/lib/auth/public-forward";

afterEach(() => vi.unstubAllGlobals());

describe("forwardPublic", () => {
  it("forwards method, body and caller address with no bearer", async () => {
    const upstream = vi.fn(async () => new Response(null, { status: 202 }));
    vi.stubGlobal("fetch", upstream);

    const request = new Request("http://next/api/auth/password-reset/request", {
      method: "POST",
      headers: { "content-type": "application/json", "x-forwarded-for": "10.0.0.7" },
      body: JSON.stringify({ email: "dev@example.com" }),
    });
    const response = await forwardPublic(request, "/auth/password-reset/request");

    expect(response.status).toBe(202);
    const [url, init] = upstream.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toMatch(/\/auth\/password-reset\/request$/);
    expect(init.method).toBe("POST");
    expect(init.body).toBe('{"email":"dev@example.com"}');
    const headers = new Headers(init.headers);
    expect(headers.get("authorization")).toBeNull();
    expect(headers.get("x-forwarded-for")).toBe("10.0.0.7");
  });

  it("relays an error envelope and status untouched", async () => {
    const envelope = {
      detail: { code: "PASSWORD_RESET_TOKEN_INVALID", message: "x" },
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Response.json(envelope, { status: 400 })),
    );

    const request = new Request("http://next/api/auth/password-reset/confirm", {
      method: "POST",
      body: "{}",
    });
    const response = await forwardPublic(request, "/auth/password-reset/confirm");

    expect(response.status).toBe(400);
    expect(await response.json()).toEqual(envelope);
  });

  it("sends no body on a GET", async () => {
    const upstream = vi.fn(async () => Response.json({ enabled: true }));
    vi.stubGlobal("fetch", upstream);
    await forwardPublic(
      new Request("http://next/api/auth/password-reset/availability"),
      "/auth/password-reset/availability",
    );
    const [, init] = upstream.mock.calls[0] as unknown as [string, RequestInit];
    expect(init.body).toBeUndefined();
  });

  it("never sets a cookie, even if the backend tries", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response("{}", {
            status: 200,
            headers: { "set-cookie": "x=y; Path=/" },
          }),
      ),
    );

    const request = new Request("http://next/api/auth/password-reset/availability", {
      method: "GET",
    });
    const response = await forwardPublic(request, "/auth/password-reset/availability");

    expect(response.headers.getSetCookie()).toHaveLength(0);
  });
});
