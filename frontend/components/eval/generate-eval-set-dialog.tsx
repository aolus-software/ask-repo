"use client";

import { FlaskConical } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { toast } from "sonner";

import { PathPicker } from "@/components/checklist/path-picker";
import { FormDialog } from "@/components/form/form-dialog";
import { Button } from "@/components/ui/button";
import { Field, FieldDescription, FieldError, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useGenerateEvalSet } from "@/hooks/use-eval";
import { isApiError } from "@/lib/api/errors";
import { useErrorText, useFieldErrorText } from "@/lib/i18n/error-text";
import type { EvalCount, EvalMix } from "@/lib/api/types";
import { PERMISSION, can } from "@/lib/can";

// Mirrors `EvalSetCreate.count: Literal[10, 25, 50]` in `backend/app/schemas/eval.py`.
// The backend owns the rule; if its options change, change this list with it.
const COUNT_OPTIONS: EvalCount[] = [10, 25, 50];

const MIXES: EvalMix[] = ["balanced", "explain", "locate"];

const EMPTY = {
  name: "",
  sourcePath: "",
  count: 25 as EvalCount,
  mix: "balanced" as EvalMix,
};

/**
 * Ask for a generated eval set. The trigger renders only for `eval.run`; hiding it is
 * cosmetic and the route's own permission check is the control.
 *
 * A path the index does not cover answers `400 MODULE_PATH_NOT_INDEXED` with no `fields`
 * map, so the message is shown against the path input here rather than in the banner.
 */
export function GenerateEvalSetDialog({
  projectId,
  permissions,
}: {
  projectId: string;
  permissions: string[];
}) {
  const t = useTranslations("eval.generateDialog");
  const tMix = useTranslations("eval.mix");
  const errorText = useErrorText();
  const fieldErrorText = useFieldErrorText();
  const [open, setOpen] = useState(false);
  const [values, setValues] = useState(EMPTY);
  const [nameBlank, setNameBlank] = useState(false);
  const mutation = useGenerateEvalSet(projectId);

  if (!can({ permissions }, PERMISSION.EVAL_RUN)) return null;

  const pathNotIndexed =
    isApiError(mutation.error) && mutation.error.code === "MODULE_PATH_NOT_INDEXED"
      ? errorText(mutation.error)
      : undefined;
  const nameError =
    (nameBlank ? t("nameRequired") : undefined) ??
    fieldErrorText(mutation.error, "name");
  const countError = fieldErrorText(mutation.error, "count");
  const mixError = fieldErrorText(mutation.error, "mix");
  const pathError = pathNotIndexed ?? fieldErrorText(mutation.error, "sourcePath");

  function handleOpenChange(next: boolean) {
    setOpen(next);
    if (!next) {
      mutation.reset();
      setNameBlank(false);
    }
  }

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!values.name.trim()) {
      setNameBlank(true);
      return;
    }

    mutation.mutate(
      {
        name: values.name.trim(),
        sourcePath: values.sourcePath.trim() || null,
        count: values.count,
        mix: values.mix,
      },
      {
        onSuccess: () => {
          toast.success(t("started"));
          setValues(EMPTY);
          setNameBlank(false);
          setOpen(false);
        },
      },
    );
  }

  return (
    <>
      <Button onClick={() => setOpen(true)}>
        <FlaskConical className="size-4" />
        {t("trigger")}
      </Button>
      <FormDialog
        open={open}
        onOpenChange={handleOpenChange}
        title={t("title")}
        description={t("description")}
        submitLabel={t("submit")}
        isPending={mutation.isPending}
        error={pathNotIndexed ? null : mutation.error}
        onSubmit={handleSubmit}
      >
        <Field>
          <FieldLabel htmlFor="eval-name">
            {t("nameLabel")} <span className="text-danger-text">*</span>
          </FieldLabel>
          <Input
            id="eval-name"
            placeholder={t("namePlaceholder")}
            value={values.name}
            onChange={(event) => {
              setNameBlank(false);
              setValues({ ...values, name: event.target.value });
            }}
            aria-invalid={Boolean(nameError)}
          />
          {nameError ? <FieldError>{nameError}</FieldError> : null}
        </Field>

        <Field>
          <FieldLabel htmlFor="eval-path">{t("pathLabel")}</FieldLabel>
          <PathPicker
            projectId={projectId}
            value={values.sourcePath}
            onValueChange={(sourcePath) => setValues({ ...values, sourcePath })}
            inputId="eval-path"
            invalid={Boolean(pathError)}
          />
          <FieldDescription>{t("pathHelp")}</FieldDescription>
          {pathError ? <FieldError>{pathError}</FieldError> : null}
        </Field>

        <Field>
          <FieldLabel htmlFor="eval-count">{t("questionsLabel")}</FieldLabel>
          <Select
            value={String(values.count)}
            onValueChange={(value) =>
              setValues({ ...values, count: Number(value) as EvalCount })
            }
          >
            <SelectTrigger
              id="eval-count"
              className="w-full"
              aria-invalid={Boolean(countError)}
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {COUNT_OPTIONS.map((option) => (
                <SelectItem key={option} value={String(option)}>
                  {option}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {countError ? <FieldError>{countError}</FieldError> : null}
        </Field>

        <Field>
          <FieldLabel htmlFor="eval-mix">{t("mixLabel")}</FieldLabel>
          <Select
            value={values.mix}
            onValueChange={(value) => setValues({ ...values, mix: value as EvalMix })}
          >
            <SelectTrigger
              id="eval-mix"
              className="w-full"
              aria-invalid={Boolean(mixError)}
            >
              <SelectValue>{(value: string) => tMix(value as EvalMix)}</SelectValue>
            </SelectTrigger>
            <SelectContent>
              {MIXES.map((mix) => (
                <SelectItem key={mix} value={mix}>
                  {tMix(mix)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {mixError ? <FieldError>{mixError}</FieldError> : null}
        </Field>
      </FormDialog>
    </>
  );
}
