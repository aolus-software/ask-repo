import type { ErrorCode } from "@/lib/api/types";

/**
 * Every API failure, in one type. Parsed from the single error shape the backend
 * guarantees (`docs/PRD.md` §5.1):
 *
 *   {"detail": {"code": "...", "message": "...", "fields"?: {...}}}
 *
 * No call site ever sees a raw fetch rejection or an unparsed body, which is what
 * lets every screen handle failure with one branch.
 */
export class ApiError extends Error {
  readonly status: number;
  readonly code: ErrorCode;
  /** Keyed by the camelCase field name. Empty when the backend named no fields. */
  readonly fieldErrors: Record<string, string>;

  constructor(
    status: number,
    code: ErrorCode,
    message: string,
    fieldErrors: Record<string, string> = {},
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.fieldErrors = fieldErrors;
  }
}

export function isApiError(error: unknown): error is ApiError {
  return error instanceof ApiError;
}

const GENERIC_MESSAGE = "Something went wrong. Please try again.";

/** Build an `ApiError` from a failed response, whatever shape its body is in. */
export async function parseApiError(response: Response): Promise<ApiError> {
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    return new ApiError(response.status, "INTERNAL_ERROR", GENERIC_MESSAGE);
  }

  const detail = (body as { detail?: unknown } | null)?.detail;
  if (!detail || typeof detail !== "object") {
    return new ApiError(response.status, "INTERNAL_ERROR", GENERIC_MESSAGE);
  }

  const { code, message, fields } = detail as {
    code?: unknown;
    message?: unknown;
    fields?: unknown;
  };
  if (typeof code !== "string") {
    return new ApiError(response.status, "INTERNAL_ERROR", GENERIC_MESSAGE);
  }

  const fieldErrors: Record<string, string> = {};
  if (fields && typeof fields === "object") {
    for (const [key, value] of Object.entries(fields as Record<string, unknown>)) {
      if (typeof value === "string") fieldErrors[key] = value;
    }
  }

  return new ApiError(
    response.status,
    code as ErrorCode,
    typeof message === "string" && message ? message : GENERIC_MESSAGE,
    fieldErrors,
  );
}

/**
 * The network never carried the request: DNS failure, refused connection, aborted
 * TLS. No Response exists, so `parseApiError` cannot help — but callers still branch
 * on `ApiError`, and a form banner renders `error.message`, so letting the raw
 * `TypeError: Failed to fetch` through would print browser jargon at the operator.
 *
 * Status 0 is the conventional "no response" marker and keeps the 4xx retry rule in
 * `lib/query/provider.tsx` from treating it as a client error.
 */
export function networkError(): ApiError {
  return new ApiError(
    0,
    "INTERNAL_ERROR",
    "Could not reach the server. Check your connection and try again.",
  );
}

/** Read one field's error. Returns undefined for anything that is not an ApiError. */
export function fieldError(error: unknown, name: string): string | undefined {
  return isApiError(error) ? error.fieldErrors[name] : undefined;
}
