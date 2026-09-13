import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

/**
 * A background job (index, generation) ended in `failed` with a scrubbed error
 * message. One treatment for one event, wherever it is shown
 * (`docs/ui-audit-findings.md` §U6.2) — a clone failure and a generation failure are
 * both "a worker stopped and left a reason", and both can legitimately contain a
 * path, so both render in `font-mono`.
 */
export function JobFailureAlert({
  title,
  message,
}: {
  title: string;
  message: string;
}) {
  return (
    <Alert variant="destructive">
      <AlertTitle>{title}</AlertTitle>
      {/* Already scrubbed by the backend, so no token can be in it (docs/PRD.md §9). */}
      <AlertDescription className="font-mono text-sm">{message}</AlertDescription>
    </Alert>
  );
}
