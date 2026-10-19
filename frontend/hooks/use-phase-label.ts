"use client";

import { useTranslations } from "next-intl";

/**
 * The wording for "what is the model doing right now", read from `ask.phases` so the
 * Ask screen and both refinement chats say the same thing. A phase this client does
 * not know yet renders as nothing rather than a missing-key error.
 */
export function usePhaseLabel(): (phase: string) => string | null {
  const t = useTranslations("ask.phases");
  return (phase) => (t.has(phase as never) ? t(phase as never) : null);
}
