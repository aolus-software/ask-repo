import { afterEach, describe, expect, it, vi } from "vitest";

import { apiFetch } from "@/lib/api/client";
import { isApiError } from "@/lib/api/errors";

afterEach(() => vi.unstubAllGlobals());

describe("apiFetch", () => {
  it("turns a network-level failure into an ApiError, not a raw TypeError", async () => {
    // A refused connection or DNS failure rejects before any Response exists, so
    // parseApiError never sees it. Callers branch on ApiError, and FormError renders
    // `error.message` — without this the operator would read "Failed to fetch".
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("Failed to fetch");
      }),
    );

    const error = await apiFetch("/projects").catch((e: unknown) => e);

    expect(isApiError(error)).toBe(true);
    if (isApiError(error)) {
      expect(error.code).toBe("INTERNAL_ERROR");
      expect(error.status).toBe(0);
      expect(error.message).not.toContain("Failed to fetch");
    }
  });

  it("still parses a real error response through the envelope", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(
            JSON.stringify({
              detail: { code: "PROJECT_NOT_READY", message: "Not ready." },
            }),
            { status: 409, headers: { "content-type": "application/json" } },
          ),
      ),
    );

    const error = await apiFetch("/projects").catch((e: unknown) => e);

    expect(isApiError(error)).toBe(true);
    if (isApiError(error)) expect(error.code).toBe("PROJECT_NOT_READY");
  });
});
