import { renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api/errors";
import { useErrorText, useFieldErrorText } from "@/lib/i18n/error-text";

describe("useErrorText", () => {
  it("translates a known code", () => {
    const { result } = renderHook(() => useErrorText());
    expect(result.current(new ApiError(404, "PROJECT_NOT_FOUND", "Project not found."))).toBe(
      "Project not found.",
    );
  });

  it("falls back to the backend message for a code with no entry", () => {
    const { result } = renderHook(() => useErrorText());
    expect(result.current(new ApiError(400, "NOT_A_REAL_CODE" as never, "Raw text."))).toBe(
      "Raw text.",
    );
  });

  it("uses the generic text for something that is not an ApiError", () => {
    const { result } = renderHook(() => useErrorText());
    expect(result.current("boom")).toBe("Something went wrong. Please try again.");
  });
});

describe("useFieldErrorText", () => {
  it("translates by field type, then falls back to the backend text", () => {
    const error = new ApiError(
      422,
      "VALIDATION_ERROR",
      "Request validation failed.",
      { name: "Field required", password: "Too common" },
      {},
      { name: "missing" },
    );
    const { result } = renderHook(() => useFieldErrorText());
    expect(result.current(error, "name")).toBe("This field is required.");
    expect(result.current(error, "password")).toBe("Too common");
    expect(result.current(error, "absent")).toBeUndefined();
  });
});
