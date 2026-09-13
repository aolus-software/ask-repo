import { RefreshCw } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { isApiError } from "@/lib/api/errors";

/**
 * A list request failed. Rendered instead of, never behind, an empty state — a failed
 * request and an empty result are different facts, and collapsing them tells a user
 * their data does not exist when the truth is the server could not be reached
 * (`docs/ui-audit-findings.md` §U7.1). `onRetry` is the query's own `refetch`, so this
 * never guesses at how to recover.
 */
export function ListError({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  const message = isApiError(error) ? error.message : "Something went wrong.";

  return (
    <div className="space-y-4">
      <Alert variant="destructive">
        <AlertTitle>Could not load this list</AlertTitle>
        <AlertDescription>{message}</AlertDescription>
      </Alert>
      <Button variant="outline" size="sm" onClick={onRetry}>
        <RefreshCw className="size-4" />
        Try again
      </Button>
    </div>
  );
}
