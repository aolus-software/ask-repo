"use client";

import { FlaskConical } from "lucide-react";
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
import { fieldError, isApiError } from "@/lib/api/errors";
import type { EvalCount, EvalMix } from "@/lib/api/types";
import { PERMISSION, can } from "@/lib/can";

const COUNT_OPTIONS: EvalCount[] = [10, 25, 50];

const MIX_LABELS: Record<EvalMix, string> = {
  balanced: "Balanced",
  explain: "Explain only",
  locate: "Locate only",
};

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
  const [open, setOpen] = useState(false);
  const [values, setValues] = useState(EMPTY);
  const mutation = useGenerateEvalSet(projectId);

  if (!can({ permissions }, PERMISSION.EVAL_RUN)) return null;

  const pathNotIndexed =
    isApiError(mutation.error) && mutation.error.code === "MODULE_PATH_NOT_INDEXED"
      ? mutation.error.message
      : undefined;
  const pathError = pathNotIndexed ?? fieldError(mutation.error, "sourcePath");

  function handleOpenChange(next: boolean) {
    setOpen(next);
    if (!next) mutation.reset();
  }

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!values.name.trim()) return;

    mutation.mutate(
      {
        name: values.name.trim(),
        sourcePath: values.sourcePath.trim() || null,
        count: values.count,
        mix: values.mix,
      },
      {
        onSuccess: () => {
          toast.success("Generation started");
          setValues(EMPTY);
          setOpen(false);
        },
      },
    );
  }

  return (
    <>
      <Button onClick={() => setOpen(true)}>
        <FlaskConical className="size-4" />
        Generate eval set
      </Button>
      <FormDialog
        open={open}
        onOpenChange={handleOpenChange}
        title="Generate an eval set"
        description="Generate questions with reference answers from this project's indexed code, to measure the assistant against."
        submitLabel="Generate"
        isPending={mutation.isPending}
        error={pathNotIndexed ? null : mutation.error}
        onSubmit={handleSubmit}
      >
        <Field>
          <FieldLabel htmlFor="eval-name">
            Name <span className="text-danger">*</span>
          </FieldLabel>
          <Input
            id="eval-name"
            placeholder="e.g., Auth questions"
            value={values.name}
            onChange={(event) => setValues({ ...values, name: event.target.value })}
            aria-invalid={Boolean(fieldError(mutation.error, "name"))}
          />
          {fieldError(mutation.error, "name") ? (
            <FieldError>{fieldError(mutation.error, "name")}</FieldError>
          ) : null}
        </Field>

        <Field>
          <FieldLabel htmlFor="eval-path">Path</FieldLabel>
          <PathPicker
            projectId={projectId}
            value={values.sourcePath}
            onValueChange={(sourcePath) => setValues({ ...values, sourcePath })}
            inputId="eval-path"
            invalid={Boolean(pathError)}
          />
          <FieldDescription>
            Leave empty for the whole project, or pick a folder or file to cover.
          </FieldDescription>
          {pathError ? <FieldError>{pathError}</FieldError> : null}
        </Field>

        <Field>
          <FieldLabel>Questions</FieldLabel>
          <Select
            value={String(values.count)}
            onValueChange={(value) =>
              setValues({ ...values, count: Number(value) as EvalCount })
            }
          >
            <SelectTrigger className="w-full" aria-label="Number of questions">
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
        </Field>

        <Field>
          <FieldLabel>Mix</FieldLabel>
          <Select
            value={values.mix}
            onValueChange={(value) => setValues({ ...values, mix: value as EvalMix })}
          >
            <SelectTrigger className="w-full" aria-label="Question mix">
              <SelectValue>
                {(value: string) => MIX_LABELS[value as EvalMix]}
              </SelectValue>
            </SelectTrigger>
            <SelectContent>
              {(Object.keys(MIX_LABELS) as EvalMix[]).map((mix) => (
                <SelectItem key={mix} value={mix}>
                  {MIX_LABELS[mix]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
      </FormDialog>
    </>
  );
}
