import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { proxy } from "@/proxy";
import { __resetRefreshFlight } from "@/lib/auth/session";

const ORIGINAL_API_URL = process.env.API_URL;

beforeEach(() => {
  process.env.API_URL = "http://backend:8000";
  __resetRefreshFlight();
});

afterEach(() => {
  process.env.API_URL = ORIGINAL_API_URL;
});

const request = (path: string, cookie = "") =>
  new NextRequest(new URL(path, "http://localhost:3000"), { headers: { cookie } });

const SESSION = "askrepo_session=askrepo_refresh%3Dopaque";
const ACCESS = "askrepo_access=jwt";

describe("the proxy gate", () => {
  it("sends an anonymous visitor to login, remembering where they were going", async () => {
    const response = await proxy(request("/projects"));
    const location = new URL(
      response.headers.get("location") ?? "",
      "http://localhost:3000",
    );

    expect(response.status).toBe(307);
    expect(location.pathname).toBe("/login");
    expect(location.searchParams.get("next")).toBe("/projects");
  });

  it("lets an anonymous visitor reach login", async () => {
    const response = await proxy(request("/login"));
    expect(response.headers.get("location")).toBeNull();
  });

  it("passes a fully authenticated request straight through", async () => {
    const response = await proxy(request("/projects", `${SESSION}; ${ACCESS}`));
    expect(response.headers.get("location")).toBeNull();
  });

  it("sends an authenticated visitor away from login", async () => {
    const response = await proxy(request("/login", `${SESSION}; ${ACCESS}`));
    const location = new URL(
      response.headers.get("location") ?? "",
      "http://localhost:3000",
    );
    expect(location.pathname).toBe("/");
  });

  it("refreshes and continues when the access cookie has expired", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(
            JSON.stringify({
              accessToken: "fresh",
              tokenType: "bearer",
              expiresIn: 900,
              user: {},
            }),
            {
              status: 200,
              headers: {
                "content-type": "application/json",
                "set-cookie": "askrepo_refresh=rotated; Path=/auth",
              },
            },
          ),
      ),
    );

    const response = await proxy(request("/projects", SESSION));

    expect(response.headers.get("location")).toBeNull();
    expect(response.headers.getSetCookie().join("\n")).toContain(
      "askrepo_access=fresh",
    );
  });

  it("clears the session and redirects when the refresh is refused", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(null, { status: 401 })),
    );

    const response = await proxy(request("/projects", SESSION));
    const location = new URL(
      response.headers.get("location") ?? "",
      "http://localhost:3000",
    );

    expect(location.pathname).toBe("/login");
    expect(response.headers.getSetCookie().join("\n")).toContain("askrepo_session=;");
  });

  it("does not include a next param when the target is the dashboard", async () => {
    const response = await proxy(request("/"));
    const location = new URL(
      response.headers.get("location") ?? "",
      "http://localhost:3000",
    );
    expect(location.searchParams.get("next")).toBeNull();
  });
});
