import { Alert, AlertDescription } from "@/components/ui/alert";
import { isApiError } from "@/lib/api/errors";
import { useErrorText } from "@/lib/i18n/error-text";

/**
 * The form-level banner, shown ONLY when the backend named no fields. When it did,
 * those messages render against their own inputs and a banner repeating them is
 * noise (`.claude/rules/forms.md` §4). Both shells use this; never add a second one.
 */
export function FormError({ error }: { error: unknown }) {
  const errorText = useErrorText();
  if (!error) return null;
  if (isApiError(error) && Object.keys(error.fieldErrors).length > 0) return null;

  return (
    <Alert variant="destructive" className="mb-4">
      <AlertDescription>{errorText(error)}</AlertDescription>
    </Alert>
  );
}
