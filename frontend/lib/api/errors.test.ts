import { describe, expect, it } from "vitest";

import { ApiError, fieldError, isApiError, parseApiError } from "@/lib/api/errors";

function jsonResponse(body: unknown, status: number): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

describe("parseApiError", () => {
  it("reads the standard envelope", async () => {
    const error = await parseApiError(
      jsonResponse({ detail: { code: "PROJECT_NOT_READY", message: "Not ready yet." } }, 409),
    );
    expect(error.status).toBe(409);
    expect(error.code).toBe("PROJECT_NOT_READY");
    expect(error.message).toBe("Not ready yet.");
    expect(error.fieldErrors).toEqual({});
  });

  it("keeps 422 field keys camelCase, exactly as the backend sent them", async () => {
    const error = await parseApiError(
      jsonResponse(
        {
          detail: {
            code: "VALIDATION_ERROR",
            message: "Invalid request.",
            fields: { repoUrl: "Must be an https URL.", newPassword: "Too short." },
          },
        },
        422,
      ),
    );
    expect(error.fieldErrors.repoUrl).toBe("Must be an https URL.");
    expect(error.fieldErrors.newPassword).toBe("Too short.");
  });

  it("turns a non-JSON body into INTERNAL_ERROR carrying the real status", async () => {
    const error = await parseApiError(
      new Response("<html>502 Bad Gateway</html>", {
        status: 502,
        headers: { "content-type": "text/html" },
      }),
    );
    expect(error.status).toBe(502);
    expect(error.code).toBe("INTERNAL_ERROR");
    expect(error.message.length).toBeGreaterThan(0);
  });

  it("turns JSON in an unexpected shape into INTERNAL_ERROR", async () => {
    const error = await parseApiError(jsonResponse({ oops: true }, 500));
    expect(error.status).toBe(500);
    expect(error.code).toBe("INTERNAL_ERROR");
  });

  it("survives an empty body", async () => {
    const error = await parseApiError(new Response(null, { status: 503 }));
    expect(error.status).toBe(503);
    expect(error.code).toBe("INTERNAL_ERROR");
  });
});

describe("fieldError", () => {
  it("returns the message for a named field", () => {
    const error = new ApiError(422, "VALIDATION_ERROR", "Invalid.", { email: "Required." });
    expect(fieldError(error, "email")).toBe("Required.");
  });

  it("returns undefined for an unnamed field, and for a non-ApiError", () => {
    const error = new ApiError(422, "VALIDATION_ERROR", "Invalid.", { email: "Required." });
    expect(fieldError(error, "name")).toBeUndefined();
    expect(fieldError(new Error("boom"), "email")).toBeUndefined();
    expect(fieldError(null, "email")).toBeUndefined();
  });
});

describe("isApiError", () => {
  it("distinguishes an ApiError from an ordinary Error", () => {
    expect(isApiError(new ApiError(404, "USER_NOT_FOUND", "Gone.", {}))).toBe(true);
    expect(isApiError(new Error("boom"))).toBe(false);
  });
});
