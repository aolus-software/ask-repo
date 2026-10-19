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
  /**
   * `detail` keys beyond `code`/`message`/`fields` — the widened-body carve-out
   * `CLAUDE.md`'s "One error shape" section documents (e.g. `409 LAST_OWNER`'s
   * `projects` array). Empty for every ordinary error; a call site checks
   * `error.code` first and only then reads a known key off `extra`.
   */
  readonly extra: Record<string, unknown>;
  /** Pydantic's error type per field, keyed like `fieldErrors`; empty when the backend sent none. */
  readonly fieldTypes: Record<string, string>;

  constructor(
    status: number,
    code: ErrorCode,
    message: string,
    fieldErrors: Record<string, string> = {},
    extra: Record<string, unknown> = {},
    fieldTypes: Record<string, string> = {},
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.fieldErrors = fieldErrors;
    this.extra = extra;
    this.fieldTypes = fieldTypes;
  }
}

/**
 * A stream's `error` event as an `ApiError`, so it renders through the same
 * translation as an HTTP failure. The status is the 200 the stream was opened with.
 */
export function apiErrorFromEvent(event: {
  code: ErrorCode;
  message: string;
}): ApiError {
  return new ApiError(200, event.code, event.message);
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

  const { code, message, fields, fieldTypes, ...extra } = detail as {
    code?: unknown;
    message?: unknown;
    fields?: unknown;
    fieldTypes?: unknown;
    [key: string]: unknown;
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

  const types: Record<string, string> = {};
  if (fieldTypes && typeof fieldTypes === "object") {
    for (const [key, value] of Object.entries(fieldTypes as Record<string, unknown>)) {
      if (typeof value === "string") types[key] = value;
    }
  }

  return new ApiError(
    response.status,
    code as ErrorCode,
    typeof message === "string" && message ? message : GENERIC_MESSAGE,
    fieldErrors,
    extra,
    types,
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
