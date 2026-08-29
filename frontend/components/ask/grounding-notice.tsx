import { AlertTriangle } from "lucide-react";

/**
 * Rendered visibly, never logged.
 *
 * `.claude/rules/rag.md` is blunt about why these exist: they do not make the model
 * honest, they make dishonesty VISIBLE — and a check whose result nothing can see is
 * not a check. A console line or a tooltip would be the same as not having them.
 */
const MESSAGES: Record<string, string> = {
  no_context:
    "Nothing relevant was found in this project, so no answer was generated from its code.",
  uncited_answer: "This answer does not cite any of the excerpts it was given. Treat it carefully.",
  unknown_paths:
    "This answer names files that were not among the excerpts retrieved. Those references may not exist.",
};

export function GroundingNotice({ warnings }: { warnings: string[] }) {
  if (warnings.length === 0) return null;

  return (
    <div className="border-warning bg-warning/10 mt-4 rounded-md border p-3">
      <div className="flex items-start gap-2">
        <AlertTriangle className="text-warning mt-0.5 size-4 shrink-0" />
        <ul className="space-y-1 text-sm">
          {warnings.map((warning) => (
            <li key={warning}>{MESSAGES[warning] ?? `Grounding warning: ${warning}`}</li>
          ))}
        </ul>
      </div>
    </div>
  );
}
