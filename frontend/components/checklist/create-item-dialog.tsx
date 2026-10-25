"use client";

import { useKindLabel } from "@/components/checklist/use-kind-label";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { toast } from "sonner";

import { FormDialog } from "@/components/form/form-dialog";
import { Field, FieldDescription, FieldError, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { useCreateChecklistItem } from "@/hooks/use-checklist-mutations";
import { useFieldErrorText } from "@/lib/i18n/error-text";
import type { ChecklistItemKind } from "@/lib/api/types";

const KINDS: ChecklistItemKind[] = ["positive", "negative"];

const EMPTY = {
  feature: "",
  testName: "",
  expectedResult: "",
  kind: "positive" as ChecklistItemKind,
};

/**
 * Add a test case by hand.
 *
 * No change set and no review step. The change-set indirection exists to keep
 * *model-authored* rows out of the checklist unreviewed; a human typing a test case is
 * already the review, and routing it through a proposal they would then approve
 * themselves is ceremony.
 *
 * Four fields, so a dialog rather than a page (`.claude/rules/forms.md` §1). Notes is
 * deliberately not here: it would make five and push this onto its own route, and a
 * note is something you add once the test has been run, not while writing it. The edit
 * dialog takes it.
 *
 * There is no status or result field either, and that is the access model rather than
 * brevity (spec 2.5) -- the server stamps `untested`, so a hand-written row cannot
 * arrive already claiming to have passed.
 */
export function CreateItemDialog({
  moduleId,
  open,
  onOpenChange,
}: {
  moduleId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations("checklist.createItemDialog");
  const kindLabel = useKindLabel();
  const fieldErrorText = useFieldErrorText();
  const [values, setValues] = useState(EMPTY);
  const mutation = useCreateChecklistItem(moduleId);
  const featureError = fieldErrorText(mutation.error, "feature");
  const testNameError = fieldErrorText(mutation.error, "testName");
  const expectedResultError = fieldErrorText(mutation.error, "expectedResult");

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!values.feature.trim() || !values.testName.trim()) return;
    if (!values.expectedResult.trim()) return;

    mutation.mutate(
      {
        feature: values.feature.trim(),
        testName: values.testName.trim(),
        expectedResult: values.expectedResult.trim(),
        kind: values.kind,
      },
      {
        onSuccess: () => {
          toast.success(t("added"));
          setValues(EMPTY);
          onOpenChange(false);
        },
      },
    );
  }

  return (
    <FormDialog
      open={open}
      onOpenChange={(next) => {
        if (!next) setValues(EMPTY);
        onOpenChange(next);
      }}
      title={t("title")}
      description={t("description")}
      submitLabel={t("submit")}
      isPending={mutation.isPending}
      error={mutation.error}
      onSubmit={handleSubmit}
    >
      <Field>
        <FieldLabel htmlFor="new-item-feature">
          {t("feature")} <span className="text-danger-text">*</span>
        </FieldLabel>
        <Input
          id="new-item-feature"
          placeholder={t("featurePlaceholder")}
          value={values.feature}
          onChange={(event) => setValues({ ...values, feature: event.target.value })}
          aria-invalid={Boolean(featureError)}
        />
        <FieldDescription>{t("featureHint")}</FieldDescription>
        {featureError ? <FieldError>{featureError}</FieldError> : null}
      </Field>

      <Field>
        <FieldLabel htmlFor="new-item-name">
          {t("testName")} <span className="text-danger-text">*</span>
        </FieldLabel>
        <Input
          id="new-item-name"
          placeholder={t("testNamePlaceholder")}
          value={values.testName}
          onChange={(event) => setValues({ ...values, testName: event.target.value })}
          aria-invalid={Boolean(testNameError)}
        />
        {testNameError ? <FieldError>{testNameError}</FieldError> : null}
      </Field>

      <Field>
        <FieldLabel htmlFor="new-item-expected">
          {t("expectedResult")} <span className="text-danger-text">*</span>
        </FieldLabel>
        <Textarea
          id="new-item-expected"
          className="min-h-24"
          placeholder={t("expectedResultPlaceholder")}
          value={values.expectedResult}
          onChange={(event) =>
            setValues({ ...values, expectedResult: event.target.value })
          }
          aria-invalid={Boolean(expectedResultError)}
        />
        <FieldDescription>{t("expectedResultHint")}</FieldDescription>
        {expectedResultError ? <FieldError>{expectedResultError}</FieldError> : null}
      </Field>

      <Field>
        <FieldLabel htmlFor="new-item-kind">{t("kind")}</FieldLabel>
        <Select
          value={values.kind}
          onValueChange={(value: string | null | undefined) =>
            setValues({ ...values, kind: (value as ChecklistItemKind) ?? values.kind })
          }
        >
          <SelectTrigger id="new-item-kind" className="w-full">
            <SelectValue>
              {(value: string) => kindLabel(value as ChecklistItemKind)}
            </SelectValue>
          </SelectTrigger>
          <SelectContent>
            {KINDS.map((value) => (
              <SelectItem key={value} value={value}>
                {kindLabel(value)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <FieldDescription>{t("kindHint")}</FieldDescription>
      </Field>
    </FormDialog>
  );
}
