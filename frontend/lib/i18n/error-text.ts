"use client";

import { useTranslations } from "next-intl";

import { isApiError } from "@/lib/api/errors";

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
    // Runtime key: guarded by t.has on the same expression.
    return t.has(error.code as never) ? t(error.code as never) : error.message;
  };
}

/**
 * One field's error. Translated by Pydantic's error type when the backend sent one;
 * otherwise the backend's own text, which is how a service-level rule such as the
 * password policy still reaches the user (spec §2.5).
 */
export function useFieldErrorText(): (error: unknown, name: string) => string | undefined {
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
