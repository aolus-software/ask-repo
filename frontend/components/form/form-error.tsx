import { Alert, AlertDescription } from "@/components/ui/alert";
import { isApiError } from "@/lib/api/errors";

/**
 * The form-level banner, shown ONLY when the backend named no fields. When it did,
 * those messages render against their own inputs and a banner repeating them is
 * noise (`.claude/rules/forms.md` §4). Both shells use this; never add a second one.
 */
export function FormError({ error }: { error: unknown }) {
  if (!error) return null;
  if (isApiError(error) && Object.keys(error.fieldErrors).length > 0) return null;

  const message = error instanceof Error && error.message ? error.message : "Something went wrong.";

  return (
    <Alert role="alert" className="border-danger text-danger mb-4">
      <AlertDescription>{message}</AlertDescription>
    </Alert>
  );
}
