"use client";

import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { FormDialog } from "@/components/form/form-dialog";
import { Field, FieldError, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { useCreateRole } from "@/hooks/use-role-mutations";
import { useFieldErrorText } from "@/lib/i18n/error-text";

const EMPTY = { name: "", description: "" };

/**
 * Two fields, so a dialog (forms.md §1). Permissions are set separately, on the
 * matrix page — a role with none does nothing, so on success the operator lands
 * there instead of having to find it.
 */
export function CreateRoleDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations("roles.create");
  const fieldErrorText = useFieldErrorText();
  const router = useRouter();
  const [values, setValues] = useState(EMPTY);
  const mutation = useCreateRole();

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    mutation.mutate(
      { name: values.name, description: values.description || undefined },
      {
        onSuccess: (role) => {
          toast.success(t("done"));
          setValues(EMPTY);
          onOpenChange(false);
          router.push(`/settings/roles/${role.id}`);
        },
      },
    );
  }

  const descriptionError = fieldErrorText(mutation.error, "description");
  const nameError = fieldErrorText(mutation.error, "name");

  return (
    <FormDialog
      open={open}
      onOpenChange={onOpenChange}
      title={t("title")}
      description={t("description")}
      submitLabel={t("submit")}
      isPending={mutation.isPending}
      error={mutation.error}
      onSubmit={handleSubmit}
    >
      <Field>
        <FieldLabel htmlFor="role-name">
          {t("fields.name")} <span className="text-danger">*</span>
        </FieldLabel>
        <Input
          id="role-name"
          value={values.name}
          onChange={(event) => setValues({ ...values, name: event.target.value })}
          aria-invalid={Boolean(nameError)}
        />
        {nameError ? <FieldError>{nameError}</FieldError> : null}
      </Field>

      <Field>
        <FieldLabel htmlFor="role-description">{t("fields.description")}</FieldLabel>
        <Input
          id="role-description"
          value={values.description}
          onChange={(event) =>
            setValues({ ...values, description: event.target.value })
          }
          aria-invalid={Boolean(descriptionError)}
        />
        {descriptionError ? <FieldError>{descriptionError}</FieldError> : null}
      </Field>
    </FormDialog>
  );
}
