import { AlertTriangle } from "lucide-react";
import { useTranslations } from "next-intl";

import { Alert, AlertDescription } from "@/components/ui/alert";

/**
 * Rendered visibly, never logged.
 *
 * `.claude/rules/rag.md` is blunt about why these exist: they do not make the model
 * honest, they make dishonesty VISIBLE — and a check whose result nothing can see is
 * not a check. A console line or a tooltip would be the same as not having them.
 *
 * Built on `Alert`'s `warning` variant rather than a hand-rolled div
 * (`docs/audit-finding-solved-logs.md` §U6.3), so "pay attention to this" looks the same way
 * everywhere in the app.
 */
const KNOWN_WARNINGS: ReadonlySet<string> = new Set([
  "no_context",
  "uncited_answer",
  "unknown_paths",
  "weak_evidence",
]);

export function GroundingNotice({ warnings }: { warnings: string[] }) {
  const t = useTranslations("ask");
  if (warnings.length === 0) return null;

  return (
    <Alert variant="warning" className="mt-4">
      <AlertTriangle />
      <AlertDescription>
        <ul className="space-y-1">
          {warnings.map((warning) => (
            <li key={warning}>
              {KNOWN_WARNINGS.has(warning)
                ? t(`groundingWarnings.${warning as "no_context"}`)
                : t("groundingWarnings.unknown", { warning })}
            </li>
          ))}
        </ul>
      </AlertDescription>
    </Alert>
  );
}
