import { describe, expect, it } from "vitest";

import { forwardedHeaders } from "@/lib/auth/forwarded";

function request(headers: Record<string, string>): Request {
  return new Request("http://localhost:3000/api/auth/login", { headers });
}

describe("forwardedHeaders", () => {
  it("relays the chain the reverse proxy set", () => {
    expect(forwardedHeaders(request({ "x-forwarded-for": "203.0.113.7" }))).toEqual({
      "x-forwarded-for": "203.0.113.7",
    });
  });

  it("relays the chain verbatim rather than appending to it", () => {
    // Appending would add an entry the backend's hop count does not expect, and
    // `TRUSTED_PROXY_HOPS` would have to be one higher than the proxies an operator
    // can actually count.
    expect(
      forwardedHeaders(request({ "x-forwarded-for": "1.2.3.4, 203.0.113.7" })),
    ).toEqual({
      "x-forwarded-for": "1.2.3.4, 203.0.113.7",
    });
  });

  it("sends nothing when there is no proxy in front to have set one", () => {
    expect(forwardedHeaders(request({}))).toEqual({});
  });
});
