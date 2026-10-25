import { RefreshCw } from "lucide-react";
import { useTranslations } from "next-intl";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { useErrorText } from "@/lib/i18n/error-text";

/**
 * A list request failed. Rendered instead of, never behind, an empty state — a failed
 * request and an empty result are different facts, and collapsing them tells a user
 * their data does not exist when the truth is the server could not be reached
 * (`docs/audit-finding-solved-logs.md` §U7.1). `onRetry` is the query's own `refetch`, so this
 * never guesses at how to recover.
 */
export function ListError({
  error,
  onRetry,
  padded = false,
}: {
  error: unknown;
  onRetry: () => void;
  /** Set when rendered directly inside a zero-padding card, so the alert does not touch its edges. */
  padded?: boolean;
}) {
  const t = useTranslations("feedback");
  const errorText = useErrorText();

  return (
    <div className={padded ? "space-y-4 p-4" : "space-y-4"}>
      <Alert variant="destructive">
        <AlertTitle>{t("listTitle")}</AlertTitle>
        <AlertDescription>{errorText(error)}</AlertDescription>
      </Alert>
      <Button variant="outline" size="sm" onClick={onRetry}>
        <RefreshCw className="size-4" />
        {t("retry")}
      </Button>
    </div>
  );
}
