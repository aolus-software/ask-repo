import { AlertTriangle } from "lucide-react";

import { Alert, AlertDescription } from "@/components/ui/alert";

/**
 * Rendered visibly, never logged.
 *
 * `.claude/rules/rag.md` is blunt about why these exist: they do not make the model
 * honest, they make dishonesty VISIBLE — and a check whose result nothing can see is
 * not a check. A console line or a tooltip would be the same as not having them.
 *
 * Built on `Alert`'s `warning` variant rather than a hand-rolled div
 * (`docs/ui-audit-findings.md` §U6.3), so "pay attention to this" looks the same way
 * everywhere in the app.
 */
const MESSAGES: Record<string, string> = {
  no_context:
    "Nothing relevant was found in this project, so no answer was generated from its code.",
  uncited_answer:
    "This answer does not cite any of the excerpts it was given. Treat it carefully.",
  unknown_paths:
    "This answer names files that were not among the excerpts retrieved. Those references may not exist.",
  weak_evidence:
    "The retrieved code may not fully cover this question. The answer names what it could not determine.",
};

export function GroundingNotice({ warnings }: { warnings: string[] }) {
  if (warnings.length === 0) return null;

  return (
    <Alert variant="warning" className="mt-4">
      <AlertTriangle />
      <AlertDescription>
        <ul className="space-y-1">
          {warnings.map((warning) => (
            <li key={warning}>
              {MESSAGES[warning] ?? `Grounding warning: ${warning}`}
            </li>
          ))}
        </ul>
      </AlertDescription>
    </Alert>
  );
}
