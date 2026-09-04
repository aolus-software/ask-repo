"use client";

import { useState } from "react";
import { toast } from "sonner";

import { KIND_LABELS } from "@/components/checklist/item-grid";
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
import { fieldError } from "@/lib/api/errors";
import type { ChecklistItemKind } from "@/lib/api/types";

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
  const [values, setValues] = useState(EMPTY);
  const mutation = useCreateChecklistItem(moduleId);

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
          toast.success("Test case added");
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
      title="Add a test case"
      description="A test you want on this checklist that generation did not propose."
      submitLabel="Add test case"
      isPending={mutation.isPending}
      error={mutation.error}
      onSubmit={handleSubmit}
    >
      <Field>
        <FieldLabel htmlFor="new-item-feature">
          Feature <span className="text-danger">*</span>
        </FieldLabel>
        <Input
          id="new-item-feature"
          placeholder="e.g., Login"
          value={values.feature}
          onChange={(event) => setValues({ ...values, feature: event.target.value })}
          aria-invalid={Boolean(fieldError(mutation.error, "feature"))}
        />
        <FieldDescription>
          The grid groups by feature. An existing name files this test alongside the
          others; a new one starts a new group.
        </FieldDescription>
        {fieldError(mutation.error, "feature") ? (
          <FieldError>{fieldError(mutation.error, "feature")}</FieldError>
        ) : null}
      </Field>

      <Field>
        <FieldLabel htmlFor="new-item-name">
          Test name <span className="text-danger">*</span>
        </FieldLabel>
        <Input
          id="new-item-name"
          placeholder="e.g., Rejects an expired reset token"
          value={values.testName}
          onChange={(event) => setValues({ ...values, testName: event.target.value })}
          aria-invalid={Boolean(fieldError(mutation.error, "testName"))}
        />
        {fieldError(mutation.error, "testName") ? (
          <FieldError>{fieldError(mutation.error, "testName")}</FieldError>
        ) : null}
      </Field>

      <Field>
        <FieldLabel htmlFor="new-item-expected">
          Expected result <span className="text-danger">*</span>
        </FieldLabel>
        <Textarea
          id="new-item-expected"
          className="min-h-24"
          placeholder="e.g., 410 with code TOKEN_EXPIRED"
          value={values.expectedResult}
          onChange={(event) =>
            setValues({ ...values, expectedResult: event.target.value })
          }
          aria-invalid={Boolean(fieldError(mutation.error, "expectedResult"))}
        />
        <FieldDescription>
          What a correct implementation should do, specifically. Not what it currently
          does — that is the result a tester records.
        </FieldDescription>
        {fieldError(mutation.error, "expectedResult") ? (
          <FieldError>{fieldError(mutation.error, "expectedResult")}</FieldError>
        ) : null}
      </Field>

      <Field>
        <FieldLabel htmlFor="new-item-kind">Kind</FieldLabel>
        <Select
          value={values.kind}
          onValueChange={(value: string | null | undefined) =>
            setValues({ ...values, kind: (value as ChecklistItemKind) ?? values.kind })
          }
        >
          <SelectTrigger id="new-item-kind" className="w-full">
            <SelectValue>
              {(value: string) => KIND_LABELS[value as ChecklistItemKind]}
            </SelectValue>
          </SelectTrigger>
          <SelectContent>
            {Object.entries(KIND_LABELS).map(([value, label]) => (
              <SelectItem key={value} value={value}>
                {label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <FieldDescription>
          Negative means the feature should refuse something — bad input, a missing
          permission, an expired token.
        </FieldDescription>
      </Field>
    </FormDialog>
  );
}
