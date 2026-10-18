"use client";

import { useTranslations } from "next-intl";

import { isApiError } from "@/lib/api/errors";

// The backend's message names what to fix (which password rule, why the URL was
// refused, which cap, role, path or model), so a generic translation would hide it;
// these stay English until the backend sends a translatable reason.
const ACTIONABLE_MESSAGE_CODES: ReadonlySet<string> = new Set([
  "WEAK_PASSWORD",
  "INVALID_REPO_URL",
  "INVALID_SORT_FIELD",
  "EXPORT_TOO_LARGE",
  "INSUFFICIENT_ROLE",
  "UNKNOWN_EVENT_TYPE",
  "FEEDBACK_REASON_NOT_APPLICABLE",
  "EMBEDDING_MODEL_CHANGED",
  "MODULE_PATH_NOT_INDEXED",
  "LLM_UNAVAILABLE",
]);

/**
 * An error as the user should read it. Translated by `ErrorCode` -- a wire contract
 * that never changes -- never by the backend's English `message`, which is the
 * fallback when a code has no entry (spec §2.4).
 */
export function useErrorText(): (error: unknown) => string {
  const t = useTranslations("errors");
  return (error) => {
    if (!isApiError(error)) return t("generic");
    if (error.status === 0) return t("network");
    if (ACTIONABLE_MESSAGE_CODES.has(error.code) && error.message) return error.message;
    // Runtime key: guarded by t.has on the same expression.
    return t.has(error.code as never) ? t(error.code as never) : error.message;
  };
}

/**
 * One field's error. Translated by Pydantic's error type when the backend sent one;
 * otherwise the backend's own text, which is how a service-level rule such as the
 * password policy still reaches the user (spec §2.5).
 */
export function useFieldErrorText(): (
  error: unknown,
  name: string,
) => string | undefined {
  const t = useTranslations("forms.validation");
  return (error, name) => {
    if (!isApiError(error)) return undefined;
    const message = error.fieldErrors[name];
    if (message === undefined) return undefined;
    const type = error.fieldTypes[name];
    // Runtime key: guarded by t.has on the same expression.
    return type && t.has(type as never) ? t(type as never) : message;
  };
}
