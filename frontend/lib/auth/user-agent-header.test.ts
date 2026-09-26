import { describe, expect, it } from "vitest";

import { userAgentHeader } from "@/lib/auth/user-agent-header";

function request(headers: Record<string, string>): Request {
  return new Request("http://localhost:3000/api/auth/login", { headers });
}

describe("userAgentHeader", () => {
  it("relays the browser's agent", () => {
    expect(userAgentHeader(request({ "user-agent": "Mozilla/5.0 (Test)" }))).toEqual({
      "user-agent": "Mozilla/5.0 (Test)",
    });
  });

  it("sends nothing when the browser sent none", () => {
    expect(userAgentHeader(request({}))).toEqual({});
  });
});
