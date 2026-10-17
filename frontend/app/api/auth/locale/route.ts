import { NextResponse } from "next/server";

import { applyLocale } from "@/lib/auth/locale-cookie";
import { isLanguage } from "@/lib/i18n/languages";

/**
 * Set this browser's language before anyone has signed in. There is no account to
 * store it on yet, so nothing reaches the backend; logging in to an account that has
 * a stored language replaces it (spec §2.2). A cookie writer under `/api/auth/*`,
 * per `.claude/rules/frontend-bff.md`.
 */
export async function POST(request: Request): Promise<Response> {
  let language: unknown;
  try {
    language = ((await request.json()) as { language?: unknown })?.language;
  } catch {
    language = undefined;
  }

  if (!isLanguage(language)) {
    return NextResponse.json(
      {
        detail: {
          code: "VALIDATION_ERROR",
          message: "Unsupported language.",
          fields: { language: "Unsupported language." },
        },
      },
      { status: 422 },
    );
  }

  const response = new NextResponse(null, { status: 204 });
  applyLocale(response, language);
  return response;
}
