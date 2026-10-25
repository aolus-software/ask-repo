import { Field, FieldLabel } from "@/components/ui/field";

/**
 * One cell of a filter row: a small visible label above its control. The control must
 * carry the same `id` as `htmlFor`, so the label names it for screen readers and
 * focuses it on click (`.claude/rules/forms.md` section 5). A placeholder or an
 * `aria-label` alone disappears the moment a value is chosen, or never shows at all.
 */
export function FilterField({
  htmlFor,
  label,
  children,
}: {
  htmlFor: string;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <Field className="gap-1">
      <FieldLabel htmlFor={htmlFor} className="text-muted-foreground text-xs">
        {label}
      </FieldLabel>
      {children}
    </Field>
  );
}
