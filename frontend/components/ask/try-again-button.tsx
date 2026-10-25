"use client";

import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";

/**
 * The one-click recovery offered when a reply ended on `finishReason: "timeout"`.
 * Shared by the Ask screen and both refinement chats (§U8.13); each caller decides
 * what resending means.
 */
export function TryAgainButton({
  onClick,
  disabled = false,
}: {
  onClick: () => void;
  disabled?: boolean;
}) {
  const t = useTranslations("ask");

  return (
    <Button
      variant="outline"
      size="sm"
      className="mt-2"
      disabled={disabled}
      onClick={onClick}
    >
      {t("conversation.tryAgain")}
    </Button>
  );
}
