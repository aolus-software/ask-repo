import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { POST } from "@/app/api/auth/login/route";

const ORIGINAL_API_URL = process.env.API_URL;

beforeEach(() => {
  process.env.API_URL = "http://backend:8000";
});

afterEach(() => {
  process.env.API_URL = ORIGINAL_API_URL;
});

function loginRequest(): Request {
  return new Request("http://localhost:3000/api/auth/login", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ email: "dev@example.com", password: "correct horse battery" }),
  });
}

function backendOk(): Response {
  return new Response(
    JSON.stringify({
      accessToken: "jwt-value",
      tokenType: "bearer",
      expiresIn: 900,
      user: { id: "u1", name: "Dev", email: "dev@example.com", isAdmin: false },
    }),
    {
      status: 200,
      headers: {
        "content-type": "application/json",
        "set-cookie": "askrepo_refresh=opaque-token; Path=/auth; HttpOnly; Secure",
      },
    },
  );
}

describe("POST /api/auth/login", () => {
  it("never returns the access token to the browser", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => backendOk()),
    );
    const response = await POST(loginRequest());
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body.user.email).toBe("dev@example.com");
    expect(JSON.stringify(body)).not.toContain("jwt-value");
  });

  it("sets both cookies httpOnly on Path=/", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => backendOk()),
    );
    const response = await POST(loginRequest());
    const cookies = response.headers.getSetCookie().join("\n");

    expect(cookies).toContain("askrepo_access=jwt-value");
    expect(cookies).toContain("askrepo_session=askrepo_refresh%3Dopaque-token");
    expect(cookies.match(/HttpOnly/gi)?.length).toBe(2);
    expect(cookies.match(/Path=\//g)?.length).toBe(2);
  });

  it("passes a 429 through with its body so the form can render it", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(
            JSON.stringify({ detail: { code: "RATE_LIMITED", message: "Too many attempts." } }),
            { status: 429, headers: { "content-type": "application/json" } },
          ),
      ),
    );
    const response = await POST(loginRequest());
    const body = await response.json();

    expect(response.status).toBe(429);
    expect(body.detail.code).toBe("RATE_LIMITED");
    expect(response.headers.getSetCookie()).toHaveLength(0);
  });

  it("passes a 401 through without setting cookies", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(
            JSON.stringify({
              detail: { code: "INVALID_CREDENTIALS", message: "Incorrect email or password." },
            }),
            { status: 401, headers: { "content-type": "application/json" } },
          ),
      ),
    );
    const response = await POST(loginRequest());
    expect(response.status).toBe(401);
    expect(response.headers.getSetCookie()).toHaveLength(0);
  });
});
