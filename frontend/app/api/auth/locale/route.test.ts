import { describe, expect, it, vi } from "vitest";

import { POST } from "@/app/api/auth/locale/route";

function post(body: unknown): Request {
  return new Request("http://localhost/api/auth/locale", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

describe("POST /api/auth/locale", () => {
  it("sets the cookie for a shipped language", async () => {
    const response = await POST(post({ language: "ko" }));
    expect(response.status).toBe(204);
    expect(response.headers.get("set-cookie")).toContain("askrepo_locale=ko");
  });

  it("refuses an unshipped language in the one error shape", async () => {
    const response = await POST(post({ language: "fr" }));
    expect(response.status).toBe(422);
    expect((await response.json()).detail.code).toBe("VALIDATION_ERROR");
  });

  it("never calls the backend", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    await POST(post({ language: "id" }));
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});
