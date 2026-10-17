import { ShieldX } from "lucide-react";
import { useTranslations } from "next-intl";

import { CenteredMessage } from "@/components/feedback/centered-message";

/**
 * Rendered in place, never a redirect (`docs/design.md` → Feedback). Used where the
 * caller may see the resource but not act on it — the 403 case (response-api.md).
 */
export function Forbidden({ message }: { message?: string }) {
  const t = useTranslations("feedback.forbidden");
  return (
    <CenteredMessage
      icon={ShieldX}
      tone="danger"
      level={2}
      title={t("title")}
      description={message ?? t("description")}
    />
  );
}
