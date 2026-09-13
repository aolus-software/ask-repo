import { Forbidden } from "@/components/feedback/forbidden";
import { NotFound } from "@/components/feedback/not-found";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { isApiError } from "@/lib/api/errors";

/**
 * The one ladder every detail screen uses to read a fetch failure
 * (`docs/ui-audit-findings.md` §U7.2): `404` is a miss and renders `NotFound`, `403` is
 * a resource the caller may see but not read this way and renders `Forbidden`, and
 * everything else — a dropped connection, a `500`, an unreachable backend — is a real
 * failure with a retry, never "not found". Reporting a network error as a deleted
 * resource is worse than admitting the request failed, especially for a conversation:
 * it is private and unrecoverable, so "not found" reads as "gone forever".
 */
export function DetailError({
  error,
  notFoundMessage,
  onRetry,
}: {
  error: unknown;
  notFoundMessage: string;
  onRetry?: () => void;
}) {
  if (isApiError(error)) {
    if (error.status === 404) return <NotFound message={notFoundMessage} />;
    if (error.status === 403) return <Forbidden message={error.message} />;
  }

  const message = isApiError(error) ? error.message : "Something went wrong.";

  return (
    <div className="space-y-4">
      <Alert variant="destructive">
        <AlertTitle>Could not load this page</AlertTitle>
        <AlertDescription>{message}</AlertDescription>
      </Alert>
      {onRetry ? (
        <Button variant="outline" size="sm" onClick={onRetry}>
          Try again
        </Button>
      ) : null}
    </div>
  );
}
