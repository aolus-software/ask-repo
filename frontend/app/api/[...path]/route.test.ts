import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { GET, POST } from "@/app/api/[...path]/route";
import { __resetRefreshFlight } from "@/lib/auth/session";

const ORIGINAL_API_URL = process.env.API_URL;

beforeEach(() => {
  process.env.API_URL = "http://backend:8000";
  __resetRefreshFlight();
});

afterEach(() => {
  process.env.API_URL = ORIGINAL_API_URL;
});

function proxyRequest(url: string, cookie: string, method = "GET"): NextRequest {
  return new NextRequest(new URL(url, "http://localhost:3000"), {
    method,
    headers: { cookie },
  });
}

const context = (path: string[]) => ({ params: Promise.resolve({ path }) });

function jsonOk(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

function unauthorized(): Response {
  return new Response(
    JSON.stringify({ detail: { code: "TOKEN_EXPIRED", message: "Expired." } }),
    {
      status: 401,
      headers: { "content-type": "application/json" },
    },
  );
}

function refreshOk(): Response {
  return new Response(
    JSON.stringify({
      accessToken: "fresh-jwt",
      tokenType: "bearer",
      expiresIn: 900,
      user: {},
    }),
    {
      status: 200,
      headers: {
        "content-type": "application/json",
        "set-cookie": "askrepo_refresh=rotated; Path=/auth; HttpOnly",
      },
    },
  );
}

describe("the proxy", () => {
  it("attaches the bearer token and forwards the query string", async () => {
    const spy = vi.fn(async () => jsonOk({ items: [] }));
    vi.stubGlobal("fetch", spy);

    const response = await GET(
      proxyRequest(
        "/api/projects?page=2&search=api",
        "askrepo_access=jwt; askrepo_session=s%3D1",
      ),
      context(["projects"]),
    );

    expect(response.status).toBe(200);
    const [url, init] = spy.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("http://backend:8000/projects?page=2&search=api");
    expect((init.headers as Record<string, string>).authorization).toBe("Bearer jwt");
  });

  it("refreshes once and retries once on a 401", async () => {
    const spy = vi
      .fn()
      .mockResolvedValueOnce(unauthorized())
      .mockResolvedValueOnce(refreshOk())
      .mockResolvedValueOnce(jsonOk({ ok: true }));
    vi.stubGlobal("fetch", spy);

    const response = await GET(
      proxyRequest(
        "/api/projects",
        "askrepo_access=stale; askrepo_session=askrepo_refresh%3Dold",
      ),
      context(["projects"]),
    );

    expect(response.status).toBe(200);
    expect(spy).toHaveBeenCalledTimes(3);
    const retry = spy.mock.calls[2] as [string, RequestInit];
    expect((retry[1].headers as Record<string, string>).authorization).toBe(
      "Bearer fresh-jwt",
    );
    expect(response.headers.getSetCookie().join("\n")).toContain(
      "askrepo_access=fresh-jwt",
    );
  });

  it("clears cookies and returns 401 when the retry also fails", async () => {
    const spy = vi
      .fn()
      .mockResolvedValueOnce(unauthorized())
      .mockResolvedValueOnce(refreshOk())
      .mockResolvedValueOnce(unauthorized());
    vi.stubGlobal("fetch", spy);

    const response = await GET(
      proxyRequest(
        "/api/projects",
        "askrepo_access=stale; askrepo_session=askrepo_refresh%3Dold",
      ),
      context(["projects"]),
    );

    expect(response.status).toBe(401);
    const cookies = response.headers.getSetCookie().join("\n");
    expect(cookies).toContain("askrepo_access=;");
    expect(cookies).toContain("askrepo_session=;");
  });

  it("refreshes first when the access cookie is already gone", async () => {
    const spy = vi
      .fn()
      .mockResolvedValueOnce(refreshOk())
      .mockResolvedValueOnce(jsonOk({ ok: 1 }));
    vi.stubGlobal("fetch", spy);

    const response = await GET(
      proxyRequest("/api/projects", "askrepo_session=askrepo_refresh%3Dold"),
      context(["projects"]),
    );

    expect(response.status).toBe(200);
    expect(spy).toHaveBeenCalledTimes(2);
  });

  it("returns 401 without calling the backend when there is no session at all", async () => {
    const spy = vi.fn();
    vi.stubGlobal("fetch", spy);

    const response = await GET(
      proxyRequest("/api/projects", ""),
      context(["projects"]),
    );

    expect(response.status).toBe(401);
    expect(spy).not.toHaveBeenCalled();
  });

  it("strips set-cookie from the backend response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(JSON.stringify({ ok: true }), {
            status: 200,
            headers: {
              "content-type": "application/json",
              "set-cookie": "askrepo_refresh=leaked; Path=/auth",
            },
          }),
      ),
    );

    const response = await GET(
      proxyRequest("/api/projects", "askrepo_access=jwt; askrepo_session=s%3D1"),
      context(["projects"]),
    );

    expect(response.headers.getSetCookie().join("")).not.toContain("leaked");
  });

  it("forwards the body and content-type on a POST", async () => {
    const spy = vi.fn(async () => jsonOk({ id: "p1" }));
    vi.stubGlobal("fetch", spy);

    const request = new NextRequest(new URL("http://localhost:3000/api/projects"), {
      method: "POST",
      headers: {
        cookie: "askrepo_access=jwt; askrepo_session=s%3D1",
        "content-type": "application/json",
      },
      body: JSON.stringify({ repoUrl: "https://github.com/o/r" }),
    });

    await POST(request, context(["projects"]));

    const [, init] = spy.mock.calls[0] as unknown as [string, RequestInit];
    expect(init.method).toBe("POST");
    expect((init.headers as Record<string, string>)["content-type"]).toBe(
      "application/json",
    );
  });

  it("preserves the SSE content type and anti-buffering headers", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response("event: token\ndata: {}\n\n", {
            status: 200,
            headers: {
              "content-type": "text/event-stream",
              "cache-control": "no-cache",
              "x-accel-buffering": "no",
            },
          }),
      ),
    );

    const response = await POST(
      proxyRequest(
        "/api/conversations/c1/messages",
        "askrepo_access=jwt; askrepo_session=s%3D1",
        "POST",
      ),
      context(["conversations", "c1", "messages"]),
    );

    expect(response.headers.get("content-type")).toBe("text/event-stream");
    expect(response.headers.get("cache-control")).toBe("no-cache");
    expect(response.headers.get("x-accel-buffering")).toBe("no");
  });
});
