"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";
import { toast } from "sonner";

import { FormDialog } from "@/components/form/form-dialog";
import { PasswordInput } from "@/components/form/password-input";
import { Field, FieldDescription, FieldError, FieldLabel } from "@/components/ui/field";
import { LanguageSelect } from "@/components/projects/language-select";
import { Input } from "@/components/ui/input";
import { useCreateProject } from "@/hooks/use-project-mutations";
import { useFieldErrorText } from "@/lib/i18n/error-text";
import type { Language } from "@/lib/i18n/languages";

const EMPTY = {
  repoUrl: "",
  branch: "main",
  pat: "",
  contentLanguage: "en" as Language,
};

export function CreateProjectDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations();
  const fieldErrorText = useFieldErrorText();
  const [values, setValues] = useState(EMPTY);
  const [urlError, setUrlError] = useState<string | undefined>();
  const mutation = useCreateProject();

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();

    // Required and shape only. The real validation — https, host allowlist, private
    // address rejection at connect time — is a security control on the backend
    // (docs/PRD.md §9) and is not mirrored here.
    if (!values.repoUrl.trim()) {
      setUrlError(t("projects.createDialog.repoUrlRequired"));
      return;
    }
    setUrlError(undefined);

    mutation.mutate(
      {
        repoUrl: values.repoUrl.trim(),
        branch: values.branch.trim() || "main",
        pat: values.pat || undefined,
        contentLanguage: values.contentLanguage,
      },
      {
        onSuccess: () => {
          // Closes on 201. The clone and index then run for minutes and progress
          // shows on the row — never hold a dialog open on a job (forms.md §10).
          toast.success(t("projects.createDialog.queued"));
          setValues(EMPTY);
          onOpenChange(false);
        },
      },
    );
  }

  const branchError = fieldErrorText(mutation.error, "branch");
  const patError = fieldErrorText(mutation.error, "pat");
  const contentLanguageError = fieldErrorText(mutation.error, "contentLanguage");
  const repoUrlError = urlError ?? fieldErrorText(mutation.error, "repoUrl");

  return (
    <FormDialog
      open={open}
      onOpenChange={onOpenChange}
      title={t("projects.createDialog.title")}
      description={t("projects.createDialog.description", {
        appName: t("common.appName"),
      })}
      submitLabel={t("projects.createDialog.submit")}
      isPending={mutation.isPending}
      error={mutation.error}
      onSubmit={handleSubmit}
    >
      <Field>
        <FieldLabel htmlFor="repoUrl">
          {t("projects.createDialog.repoUrl")}{" "}
          <span className="text-danger-text">*</span>
        </FieldLabel>
        <Input
          id="repoUrl"
          className="font-mono"
          placeholder={t("projects.createDialog.repoUrlPlaceholder")}
          value={values.repoUrl}
          onChange={(event) => setValues({ ...values, repoUrl: event.target.value })}
          aria-invalid={Boolean(repoUrlError)}
        />
        {repoUrlError ? (
          <FieldError>{repoUrlError}</FieldError>
        ) : (
          <FieldDescription>{t("projects.createDialog.repoUrlHint")}</FieldDescription>
        )}
      </Field>

      <Field>
        <FieldLabel htmlFor="branch">{t("projects.createDialog.branch")}</FieldLabel>
        <Input
          id="branch"
          className="font-mono"
          value={values.branch}
          onChange={(event) => setValues({ ...values, branch: event.target.value })}
          aria-invalid={Boolean(branchError)}
        />
        {branchError ? <FieldError>{branchError}</FieldError> : null}
      </Field>

      <Field>
        <FieldLabel htmlFor="contentLanguage">
          {t("projects.createDialog.contentLanguage")}
        </FieldLabel>
        <LanguageSelect
          id="contentLanguage"
          value={values.contentLanguage}
          onChange={(contentLanguage) => setValues({ ...values, contentLanguage })}
        />
        <FieldDescription>
          {t("projects.createDialog.contentLanguageHint")}
        </FieldDescription>
        {contentLanguageError ? <FieldError>{contentLanguageError}</FieldError> : null}
      </Field>

      <Field>
        <FieldLabel htmlFor="pat">{t("projects.createDialog.pat")}</FieldLabel>
        <PasswordInput
          id="pat"
          autoComplete="off"
          value={values.pat}
          onChange={(event) => setValues({ ...values, pat: event.target.value })}
          aria-invalid={Boolean(patError)}
        />
        {patError ? (
          <FieldError>{patError}</FieldError>
        ) : (
          // Write-only, and never a masked placeholder that looks like a value: the
          // API never returns a PAT, so a placeholder would be a lie an operator
          // submits thinking it is the real one (forms.md §9).
          <FieldDescription>{t("projects.createDialog.patHint")}</FieldDescription>
        )}
      </Field>
    </FormDialog>
  );
}
