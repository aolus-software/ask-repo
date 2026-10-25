"use client";

import { useTranslations } from "next-intl";

import type { FinishReason } from "@/lib/api/types";

/**
 * The quiet note under a reply that did not finish normally (`finishReason` other than
 * `stop`). The stored message list, the Ask screen and both refinement chats all
 * render it from here, so a cut-off reply reads the same live as after a reload
 * (`docs/ui-audit-findings.md` §U8.16). A disconnect reads `ask.interruptedNote`, the same
 * sentence `InterruptedNote` shows live, so the wording does not change across a reload
 * (§U8.11). Renders nothing for a normal finish.
 */
export function EndedEarlyNote({
  reason,
}: {
  reason: FinishReason | null | undefined;
}) {
  const t = useTranslations("ask");

  if (!reason || reason === "stop") return null;

  return (
    <p className="text-muted-foreground mt-2 text-xs">
      {reason === "disconnected"
        ? t("interruptedNote")
        : t("messages.endedEarly", { reason })}
    </p>
  );
}
