import { FileQuestion } from "lucide-react";
import { useTranslations } from "next-intl";

import { CenteredMessage } from "@/components/feedback/centered-message";

/** The 404 case — where the caller may not learn the resource exists at all. */
export function NotFound({ message }: { message?: string }) {
  const t = useTranslations("feedback.notFound");
  return (
    <CenteredMessage
      icon={FileQuestion}
      level={2}
      title={t("title")}
      description={message ?? t("description")}
    />
  );
}
